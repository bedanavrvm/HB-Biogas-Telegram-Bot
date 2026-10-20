# Platform independence: gated pilots without disrupting Telegram

Plan revision: **18 - 20 October 2026**. P2a starts the closed Complaints read
integration under ADR 0070 and the user's explicit agreement to begin now.
Native company login, existing Complaint permissions, list/search/paging,
selected detail and bounded history are connected using synthetic isolated
data. Development now runs alongside remaining M1 operational work. Real
staff admission still requires M1, named readers, privacy review and human
acceptance. Production stays disabled/unmounted. Current evidence, rollback
and unresolved gates are in the release checklist.

Historical revision 17 / P1b.2b.4 hardens the dormant browser
abuse boundary under ADR 0069: native proxy/IP policy for durable limits, HMAC
native cache keys, honest throttle/unavailable responses and activation checks
for a reviewed shared cache. The default cache remains local; this slice does
not supply or accept a shared service. Current handoff: release checklist.
Actual delivery/support, shared-cache/worker and staging M0/M1 acceptance remain
open before the Complaints read pilot. Production stays disabled/unmounted.

Historical revision 16 / P1c.6 connects guided existing-account
invitation, first-password, local QR enrollment and one-time recovery handoff
in the closed React/ADS client under ADR 0068. The local onboarding UI gap is
closed; actual delivery/support and operational readiness/M0/M1 remain open.
Next: accept the closed Complaints candidate and complete readiness/staging
before any operational Complaints read pilot. P3 writes remain a separate gate.
Required pilot order:

**Complaints → TAT → Origination → Portal.**

Historical P1c.5 follows the user's proceed/usability instructions under ADR 0067. Real
native authentication is tested against synthetic accounts in an isolated full
schema; the fixed-value preview stays separate. Stale owned cookies permit a
fresh sign-in, without converting unrelated Admin/other-channel sessions. No
new operational route, staff admission, workflow authority or M1 acceptance is
introduced. Current results/checklist: decision section 11. Next: short guided
initial setup/enrollment/recovery handoff and remaining identity/support gates.

P1c.4 follows the user's instruction to fix the researched issues and always
consult Atlassian docs. Focused access tasks keep descriptions/errors/fields in
one sequence; the workspace uses Navigation System; surfaces/selection semantics
follow official guidance; /review.html isolates synthetic scenario controls.
Four exact ADS packages and their changed graph are archive/licence/asset/peer
reviewed under ADR 0066. Current evidence and handoff: decision section 10.
This corrects earlier composition claims without opening auth, Telegram or M1.

Historical P1c.3 implemented the approved viewport plan: wider ADS grids put bounded fields,
guidance/status and compact preview controls alongside one another on desktop;
workspace/help/recovery layouts use horizontal space. Smaller token spacing and
a compact footer remove unnecessary vertical overhead. Explicit short-laptop
checks cover all pages/form errors, controls open/closed and both themes. Mobile
and enlarged text retain natural scrolling. Historical evidence/checklist: decision
section 9. No dependency, backend, schema, grant, Telegram or activation change.

Status: **P1a/P1b closed identity backends, P1c.4 synthetic ADS pages and P1c.5 native sign-in and P1c.6 guided closed onboarding are present. Browser authentication is globally disabled, production routes unmounted and M0/M1 operational acceptance open.** The exact browser graph is locally accepted under the user's implementation instructions, with an explicit peer exception, fixed development parser, notices and asset exclusions (ADR 0066). These bounded slices do not authorize merge/deployment or real staff admission. Current backend contracts are in STAFF_BROWSER_LIFECYCLE/JSON_AUTH/ENROLLMENT/REPLAY_GUARD/INITIAL_SETUP.md; frontend scope and evidence are in BROWSER_REACT_ADS_DECISION.md section 12 and browser/DEPENDENCIES.md.

Historical P1c.2 implements the user's full browser design adoption request: all current
browser pages now compose ADS layout/typography/navigation/form components and
typed semantic tokens. Native review selectors, custom CSS, global font/focus
overrides and broad lint exemptions are removed. Both ADS recommended lint sets
are blocking, including advisory guidance. Two already-reviewed packages become
direct dependencies; the archive graph and overrides stay unchanged. Exact
source-bound runtime token checks, evidence and checklist: decision section 8.
This browser-only design work does not authorize Telegram Phase 6 or activate
browser authentication. Actual transport and operational M0/M1 remain open.

Historical D13a follow-up: exact forensic graph/archive evidence is collected (529 unique
archives / 546 entries, zero remaining inspection errors). It exposes an
incompatible original React peer plus open notice/asset/licence questions; the
override-assisted graph is **not approved for installation**. Current results and
merge checklist: BROWSER_REACT_ADS_DECISION.md section 5. Application runtime is
unchanged by D13a; no frontend or production activation is claimed.

Historical P1c preparation includes a local synthetic access wireframe: run
`python scripts/serve_browser_access_preview.py` and open http://127.0.0.1:8765/.
It has fixed demo values and no API/authentication or business access. No React
workspace, ADS assets, dependency installation, D13 acceptance or M1 is claimed.
Exact scope, browser evidence and checklist: BROWSER_REACT_ADS_DECISION.md section 6.

P1c.1 supersedes the local no-install status with actual ADS components in the
isolated `browser/` workspace. After its documented build, run
`python scripts/serve_ads_browser_preview.py` and open http://127.0.0.1:8766/.
The exact dependency review binds 555 lock entries/528 archives; 134 installed
peer declarations pass with one documented legacy context exception. The fixed
selector-parser build override and supported ESLint give a zero-finding local
npm audit. Demo values remain fixed/read-only and no auth/business API is
connected. Section 7 records scope, actual browser evidence and remaining gates.

P1b.2b.1 follow-up supersedes the earlier no-enrollment source status: three
closed-backend TOTP enrollment/recovery-handoff handlers are now present, using
native forms and transactional audit. Production remains off/unmounted; no
provisioning, operational recovery, UI or M1 acceptance is claimed. Exact scope,
verification and release checklist: codebase-analysis-docs/assets/STAFF_BROWSER_ENROLLMENT.md.

Execution update: D1 is explicitly **Django accounts + django-allauth TOTP/recovery**, not an inferred fallback. D2 is **browser convenience, possible Telegram exit later**. D3 uses **current Django Complaints roles/group scope**, with no new grants. Production release/migrations are **unknown**, as confirmed by the user. The user separately approved **browser MFA first; preserve Telegram signed-launch access**. The bounded foundation may be built locally while deployment/support/acceptance gates remain open; this is not permission to activate the browser channel. See codebase-analysis-docs/assets/STAFF_BROWSER_MFA_FOUNDATION.md and ADR 0060. Every phase/merge/deployment handoff uses codebase-analysis-docs/assets/PLATFORM_INDEPENDENCE_RELEASE_CHECKLIST.md.

Source investigation baseline: 7217791e9836986a493559254f465555ed670568; documentation revision workspace: 9612b1ab4a76f0445574996c333171a07fdd99ce. The architectural research is in codebase-analysis-docs/assets/PLATFORM_INDEPENDENCE_RESEARCH.md. All repository references are relative to the repository root.

## 1. What changed after review

- Removed the unsupported containment-time, error-percentage, latency-percentile and pilot-success thresholds. Small-cohort acceptance uses scripted journeys, observed outcomes and named human review.
- Replaced the broad dated rollout with a funded-discovery decision and conditional pilot windows. Later applications are an ordered backlog, not an approved delivery commitment.
- Made **D1 identity provider, D2 business driver and D3 first audience** the first decisions. The former D2 cookie/origin decision moves to D10.
- Moved actual data-flow/privacy screening and maintenance ownership into P0. A compliance-driven project requires a qualified privacy review before choosing its remedy.
- Distinguished source findings from tested or deployed behavior. “Present in source” never means “operational in production.”
- Reordered pilots to **Complaints, TAT, Origination, Portal**. HB Deposits is a candidate Portal write, not the first platform pilot.
- Added a mandatory **M3 investment review after the Complaints read/write pilot** before commissioning TAT or later apps.
- Budgeted governance, regression, rehearsals, user acceptance and support as work, not incidental paperwork. A named backup maintainer is required before operational browser access.
- Added the user's **separate React browser frontend with Atlassian Design System (ADS)** direction. This supersedes the earlier no-SPA constraint only for new browser pages. Existing Telegram templates, JavaScript and Design Lab migration hold remain unchanged.
- Added D13: exact package/transitive/asset licence review and compatible build-tool selection before installation. Metadata-only Apache declarations do not establish permission for all ADS materials. See codebase-analysis-docs/assets/BROWSER_REACT_ADS_DECISION.md and ADR 0062.
- Split P1b.2: the dormant JSON/storage contract can proceed while frontend licensing is reviewed; usable authentication/enrollment/recovery and the React foundation remain separate unaccepted work.
- Added **D13a exact-graph review tooling/evidence**, without installing the frontend or changing runtime. The candidate, review-only lock and archive inventory are analysis artifacts, not dependency approval. See section 5 of BROWSER_REACT_ADS_DECISION.md for execution/results and unresolved gates.

The first decision is whether a second channel solves a real business need at a supportable cost—not whether every historical endpoint can be made browser-accessible.

**Findings:** the implementation direction is additive; D1–D3 now have user decisions. **Open questions:** provisioning/recovery owners, deployment evidence and staffing. **Next steps:** complete the bounded foundation and its acceptance evidence, not the entire backlog.

## 2. Business driver and what counts as success

Select a primary driver and identify any secondary goals. The following are not interchangeable:

| Driver | Minimum meaningful outcome | What must not be claimed |
|---|---|---|
| Browser convenience | Approved staff complete selected tasks in an ordinary browser, using existing authority and records | That intake, onboarding or integration processing works without Telegram |
| Telegram outage continuity | The named operating scenario works with Telegram API, SDK, launchers and message input unavailable | Continuity based only on viewing already-created records |
| Planned Telegram exit | All required business, identity, notification, support and evidence paths have accepted replacements and a decommission plan | That four narrow pilots justify retiring the bot |
| Privacy/compliance remediation | Qualified review identifies actual processing risks and the chosen controls demonstrably address them | That company branding, SSO or a browser URL itself establishes compliance |

For a convenience pilot, document remaining Telegram dependencies as exclusions. If the primary driver is continuity or exit, those dependencies are release blockers for the continuity claim, not items to quietly leave until the end.

If compliance is the driver, review actual collection, disclosure, storage, processors, retention, transfers and recovery early. The review may recommend minimizing chat data, access or retention without building a new channel at all. ODPC's assessment framework asks about actual information flows; its official guidance catalogue includes transfer and DPIA material. This plan is not a legal opinion and does not establish JBL's obligations or compliance. [R7]

**Findings:** D2 selects browser convenience with a possible future exit, not proven outage continuity or compliance remediation. **Open questions:** which ordinary staff journeys provide sufficient benefit. **Next steps:** validate Complaints convenience before expanding.

## 3. Evidence, estimates and timeline discipline

### 3.1 What is and is not established

| Evidence level | Current status |
|---|---|
| Source inspection | Django user/profile links, workflow grants, authenticators, service methods, routes, tests and release controls are present in inspected source |
| Documentation validation | Repository references and selected source hashes can be checked; this proves reference consistency only |
| Test execution | Original research ran no application tests. Later phase-specific local results and their limits are recorded in STAFF_BROWSER_MFA_FOUNDATION.md, STAFF_BROWSER_LIFECYCLE.md and STAFF_BROWSER_JSON_AUTH.md; none proves deployment |
| Staging behavior | Company login, adapter parity, rollback, current-device behavior and coexistence have not been demonstrated |
| Production behavior | Deployed commit/configuration, applied migrations, incidents, provider state, traffic baseline and actual access were not inspected |
| Operational support | Identity-provider ownership, staff coverage, available maintainers and support capacity are unresolved |

Read inspected code as a starting hypothesis about behavior. Re-read any changed file and run the affected boundary before implementation or release claims.

### 3.2 Conditional milestone windows

**P0 is timeboxed to one–two working weeks.** Its output may be a go decision, a narrower proposal or an evidence-backed stop. Do not turn it into an open-ended enterprise audit.

The following initial engineering windows are **unvalidated planning allowances**, originally assuming a usable managed IdP, dedicated engineering/QA capacity and timely decisions. The selected self-managed option adds provisioning, enrollment, recovery, abuse protection, mail delivery, cache and helpdesk work. Re-estimate P1 rather than assuming the original window covers that work. Review waiting time, missing staging, existing defects and support constraints are not concealed inside estimates.

| Phase/milestone | Conditional window | Outcome and commitment boundary |
|---|---|---|
| P0 / M0 | One–two working weeks | Decide D1–D3; pilot manifest, baseline, privacy screening, support owner and go/no-go |
| P1 / M1 | Re-estimate for self-managed authentication, licence review and a separately maintained React build; no new deadline inferred | Complete company authentication and reviewed React browser foundation accepted in staging; dormant backend slices alone are not M1 |
| P2 / M2 | Indicatively two–three working weeks after M1 | Restricted Complaints list/detail/history pilot; scripted and human-reviewed acceptance |
| P3 / M3 | Indicatively two–four working weeks after M2, only if a write is justified | One bounded Complaints write; explicit business/security/support review before further investment |
| P4 / M4 | **Not scheduled before M3** | TAT pilot, independently estimated and approved |
| P5 / M5 | **Not scheduled before M4 review** | Origination pilot, independently estimated and approved |
| P6 / M6 | **Not scheduled before M5 review** | Portal pilot; HB Deposits considered here, not earlier |
| P7 / M7 | **Only if continuity/exit is in scope** | Accepted operational drill and handover for the exact named scope; not automatic Telegram retirement |

The previous whole-programme calendar is withdrawn. No credible end date for all four apps exists until the first pilot establishes actual effort and support load. Do not compress observation or security work to preserve a date.

The former external-IdP build gate is superseded by the user's explicit self-managed choice in ADR 0060. P1a is a disabled, non-operational integration foundation. P1b must implement and accept provisioning, mandatory enrollment, recovery, abuse protection, session lifecycle, audit and support before M1 or browser activation. P2 cannot begin operational admission until M1 is accepted. Django passwords plus MFA are **not** an automatic fallback and a dependency install is not operational readiness.

**Findings:** discovery has a timebox; implementation dates are conditional estimates. **Open questions:** staffing, provider availability and actual governance effort. **Next steps:** re-estimate the first tranche at M0 and make a new investment decision at M3.

## 4. Decisions, staffing and governance budget

### 4.1 Decision register

| ID | Decision | Owner to name | Gate |
|---|---|---|---|
| D1 | Selected: existing Django accounts + allauth TOTP/recovery; provisioning/recovery owners still unnamed | IT plus security owner | Selected by user; operational support required before activation |
| D2 | Selected: browser convenience with possible exit later | Business sponsor | Validate benefit in the Complaints pilot; no continuity claim |
| D3 | Selected: current Django Complaints roles and group scope | Complaints owner | Choose actual pilot accounts before enrollment; no new grants |
| D4 | Provider binding, application-session expiry and revocation | IT/security plus backend lead | Before M1 |
| D5 | First bounded Complaints write, if justified | Complaints owner | Before P3; proposed candidate is an existing resolution comment |
| D6 | Notification/disclosure alternatives needed for the chosen driver | Owning workflow and privacy owner | Before related delivery changes |
| D7 | Production release, migration and rollback authority | Release operator/sponsor | Each production change |
| D8 | Scope and business value of the next app | Sponsor plus next workflow owner | At M3, then each app review |
| D9 | Assurance for later approval, signing or financial actions | Business/security owners | Before those actions enter scope |
| D10 | Browser origin, cookie/session assurance and CSRF topology | Technical/security lead | Before M1; previously D2 in revision 1 |
| D11 | Actual data-flow/privacy risks and required professional assessment | Named privacy/compliance owner | Screening in P0; blocking assessment before a compliance remedy is chosen |
| D12 | Primary and backup maintainer, release coverage and helpdesk capacity | Sponsor/operations owner | Before production pilot admission |
| D13 | Bounded local React/ADS graph/build accepted under “resolve it and proceed”; exact exceptions/notices/asset exclusions in ADR 0066 and browser/DEPENDENCIES.md | Repository maintainer; operational primary/backup and distribution reviewer still required | Local installation/build only; human design, production distribution and operational M1 remain open |

For the selected D1 option, prove controlled account provisioning, verified email/password setup, MFA enrollment, encrypted secrets, recovery, shared abuse/replay controls and support ownership. A company credential or email domain does not confer workflow grants. No automatic email/name-based identity linking or account conversion is allowed.

### 4.2 Capacity and bus factor

The initial windows assume two experienced engineers with QA availability, part-time IT/security and an available Complaints champion. **That staffing is not confirmed.** If one person must build, operate, recover accounts and support both channels, re-estimate and consider stopping at a small read-only scope.

Before admitting production users, name a backup who can follow the login/recovery runbook, contain the browser surface, inspect a failed submission safely, find release evidence and escalate incidents. Rehearse that handoff with the primary maintainer unavailable. A document without someone able to use it does not reduce the bus factor.

Do not require a large team merely to perform P0. Assign the small discovery effort and identify missing capacity honestly.

### 4.3 Budget required governance as delivery work

The repository requires structural ADRs, explicit approval for dependencies/access changes/production deployments, migration rollback paths, scoped tests, PostgreSQL checks where applicable, UI review and release records. Retain those requirements; do not add a duplicate bureaucracy.

Estimate and track these lines separately for every bounded work package:

| Work | Budget and completion evidence |
|---|---|
| Design/security/decision | Reviewed ADR or decision entry at the required boundary; wait for approvals is visible |
| Implementation | Small adapter/service/schema change, not unrelated refactoring |
| Test and compatibility | Narrow tests first, both-channel regression, supported PostgreSQL and cached-client checks |
| Migration/release rehearsal | Actual applicable migration, worker and rollback evidence; no pretend rehearsal for a docs-only change |
| UI review | Required source-bound review/evidence; no unauthorized Design Lab migration |
| User acceptance | Ordinary-role champion plus explicit denial/recovery journeys |
| Release/support | Operator availability, observation, incident response and next review |
| Handover | Primary/backup practice and owner acceptance |
| Browser frontend ownership | Separate React build/lockfile, ADS component/token/lint conformance, accessibility, supply-chain review, hashed assets and rollback; legacy Telegram tooling continues independently |

At M0 put actual staff-days and dependencies against these lines. Governance and acceptance may take as much time as coding; do not bury them in a small blanket buffer or present guessed fractions as measured effort. Reuse the existing private release record and link evidence once.

**Findings:** maintainability and approvals are prerequisites, not final-week paperwork. **Open questions:** named owners and available effort. **Next steps:** settle D1–D3, D11 and D12 in discovery.

## 5. Non-disruption and trust-boundary contract

The objective is no planned interruption to current Telegram use, not a zero-risk guarantee for shared-backend changes.

1. Keep existing Telegram bot/webhook identity, launchers, URLs, authentication gates, staff bindings and notification defaults unchanged unless separately authorized.
2. Keep one canonical Django staff user and one set of owning business records. No second case database, automatic identity merge, grant backfill or historical signature/audit rewrite.
3. Browser access is an additional restrictive admission rule, intersected with current workflow authority. It never replaces AccessGrant, creates business grants or supplies production access=None.
4. A valid company login is authentication, not business authorization. Roles remain independent in Complaints, TAT, Origination and Portal; preserve scoped IT and the existing active-Superuser exception.
5. Add **separate browser endpoints** with session assurance and enforced CSRF that call shared query/command services. Never add a session fallback to an existing CSRF-exempt Telegram endpoint. Invalid explicit credentials do not fall through to another identity. [R1, R4]
6. Keep session/CSRF cookies and provider secrets controlled. Decide D10 explicitly; do not globally relax cookie domains, CSRF origins or framing to make a test pass.
7. Recheck active local status and current grants on operational requests. Define and demonstrate revocation of already issued Django sessions: disabling an employee at the IdP alone is insufficient proof.
8. Shared JavaScript/templates are production Telegram dependencies. Every change to core/static/miniapp/utils.js, core/static/miniapp/portal_api.js, Complaint client helpers or shared navigation must be tested in both channels.
9. Rehearse old/cached Telegram WebViews with new server/assets and old/new worker overlap. Query-string cache busting alone is not evidence of compatibility.
10. Preserve existing row locks, revisions, retry keys, audit attribution, evidence ownership, signed bytes and external-operation semantics across channels.
11. Browser containment closes its affected surface without unnecessary global Portal maintenance, grant removal or invalidation of unrelated Telegram users.
12. If an operation needs a lock, worker drain or downtime that breaks this objective, postpone it or seek a separately approved maintenance window. Do not hide it under a platform “zero-downtime” label.
13. React is the new browser presentation layer, not a second source of rules, roles or records. Prefer same-origin Django session/CSRF requests; no client-stored auth tokens, Telegram SDK dependency or wholesale reuse of Telegram CSS/JavaScript. Browser-only assets must not replace existing Mini App assets.

Existing sources: core/services/telegram_identity.py, core/services/workflow_access.py, core/services/miniapp_requests.py, core/api/complaint_case_views.py, origination/auth.py, core/api/portal_views.py and core/services/portal_maintenance.py.

Proposed namespaces—not existing deployed routes—are /staff/ for the browser shell and /api/staff/<workflow>/ for reviewed session-authenticated endpoints. Start with complaint_cases only. The existing Telegram route surface keeps its credential policy. A company hostname with same-origin browser API may help cookie isolation, but D10 must consider actual deployment/link generation; it is not automatically required. [R5, R6]

The selected implementation authenticates the existing Django user directly through allauth; no second employee identifier or automatic name/email/phone merge is introduced. If OIDC is added later, use verified issuer/subject binding and a separately reviewed maintained integration. Keep credentials/tokens out of browser storage and avoid hand-rolled authentication. [R2, R3]

**Findings:** the new channel must not become a shortcut around existing authority or a new dependency for Telegram. **Open questions:** exact IdP/session/origin configuration. **Next steps:** express this contract as adapter and coexistence tests before activation.

## 6. Phased work and milestone gates

Programme phases P0–P7 below are unrelated to the Design Lab “Phase 6” UI migration; its separate explicit approval requirement remains.

### P0 — Focused discovery: one–two working weeks

**Goal:** settle the driver, provider, first audience and minimum viable pilot rather than inventorying every workflow in depth.

Work:

- Confirm D1–D3 early. Record unavailable IdP/MFA/administrator support as a decision blocker, not an assumption.
- Map the Complaints list/detail/comment candidate: accepted credentials, actor resolution, capabilities, group/branch scope, input/output fields, read side effects, revision, retry, audit and external publication.
- Capture a limited Telegram baseline with permitted isolated scripted tests and current CI evidence. If authorized production inspection is unavailable, mark it unverified; do not label the baseline operationally validated.
- Identify the deployed-state/migration/runner information needed for release. Seek only authorized read-only checks; do not repair production.
- Screen actual data flows: browser → Django; bot/chat/file ingestion; Drive/Sheets; IdP; email/SMS; logs/monitoring; backups and staff devices. Identify processor ownership, actual locations/contracts, retention and transfers to be reviewed. Keep private/customer details out of Git.
- For a compliance driver, commission the qualified review and determine whether a DPIA or other assessment is needed. Do not select browser migration as the legal remedy in advance.
- Inspect pilot hidden dependencies and name owners for Sheet publication, group-based scope, intake, onboarding and recovery.
- Identify the primary/backup maintainer and estimate coding, governance, QA, staging, UAT and support separately.
- Read docs/ui-standard/README.md and docs/ui-standard/component-index.md before future UI work; prepare the smallest required structural decision and release brief.

**M0 outcome:** a concise endpoint/side-effect manifest, source/test/production evidence status, D1–D3 answers, early privacy/support findings, estimates and explicit go/hold/no-go. Full staging construction, IdP procurement, a platform-wide audit or unresolved privacy remediation may be follow-up work, not reasons to extend discovery indefinitely.

**Telegram impact:** none. **If D1 fails:** no P1/P2 build; choose an independently scoped identity/support project or defer. **If no driver/value is demonstrated:** stop with Telegram unchanged.

### P1 — Company login and closed browser foundation

**Entry:** user-selected self-managed Django/allauth approach and structural/dependency approval for the dormant local foundation. Operational M0 evidence, support readiness and D4/D10 acceptance remain required before M1/activation.

P1 is split into **P1a dormant integration**, **P1b governed staff authentication** and **P1c reviewed React/ADS browser foundation**. P1a adds no production login, enrollment, recovery or business routes; its activation check deliberately fails if enabled. P1b/P1c must supply accepted operational flows and reviewed UI. The complete P1 outcome below is not claimed by a dormant backend slice.

P1b is delivered in bounded parts: **P1b.1 backend admission/revocation** adds
explicit staff opt-in, active-Superuser audit/retry/revision controls and
browser-only generation revocation/reset, while keeping admission globally off.
**P1b.2a JSON/storage contract** adds four unmounted session/password/MFA/logout
handlers over the pinned allauth browser implementation, a durable login audit
gate and encrypted expiring pending-enrollment storage. No enrollment, recovery,
business or generic allauth route is exposed. See
codebase-analysis-docs/assets/STAFF_BROWSER_JSON_AUTH.md.

**P1b.2b operational authentication** must complete controlled provisioning,
verified address/password setup, enrollment/recovery, shared abuse/replay cache,
mail/support and offboarding acceptance. Its first bounded backend increment,
**P1b.2b.1**, now adds three unmounted CSRF-protected enrollment handlers using
the pinned native password/TOTP/recovery flows. Begin rechecks the password;
activation and one-time code disclosure have transactional audit receipts.
Setup does not issue MFA assurance: explicit logout and a new native password/
MFA login follow. See codebase-analysis-docs/assets/STAFF_BROWSER_ENROLLMENT.md.
This is not completed provisioning, operational recovery or a usable UI.
**P1b.2b.2** adds shared one-use TOTP claims to the closed native browser MFA
input before authentication is saved. It uses a bounded domain table and native
code normalization without changing the global cache. It does not complete
native shared rate-limit caching or accept general worker/cache operation.
See ADR 0064 and STAFF_BROWSER_REPLAY_GUARD.md for schema, expiry, failure,
verification and rollback. No production route or browser flag is opened.
**P1b.2b.3** adds exact-account Superuser preparation and closed native mailbox/
first-password handlers for admitted non-Admin accounts with unusable passwords.
It sends/exports no proof and grants no login/MFA/business authority. Native
password changes affect that account's Django session hash; signed Telegram
identity and grants remain. See ADR 0065 and STAFF_BROWSER_INITIAL_SETUP.md.
Remaining increments must separately cover accepted provisioning delivery/UI,
usable-password address verification/recovery, interrupted setup/helpdesk, native shared replay cache,
accepted notification behavior, operational support and staging acceptance.
**P1b.2b.4** now applies the pinned native proxy/IP policy to the browser's
database limits (including anonymous setup), protects native cache keys through
Django's key hook and preserves native throttling as JSON 429. Native/cache
failure never falls back to another identity or returns bad-credential feedback.
E007/E008 additionally block activation without a reviewed shared backend and
privacy hook; E006 still blocks the unreleased product. The unchanged local
backend is not shared-cache acceptance. See ADR 0069 and the current addendum in
STAFF_BROWSER_REPLAY_GUARD.md for operation, privacy, verification and rollback.
No dormant slice satisfies M1 or usable browser access.

**P1c React/ADS frontend foundation**, before any operational P2 pilot:

1. Complete D13: proposed exact direct versions, resolved transitive licences,
   downloaded-artifact licence/notice inspection, icon/font/brand terms, permitted
   standalone use and reviewer decision. Record omissions/uncertainty; seek
   qualified clarification when necessary. Do not silently substitute a library.
   D13a is the current evidence-only slice: review inputs/reports and the offline
   inspector live in analysis assets. Collected metadata/hashes do not replace
   acceptance of licence exceptions, assets, notices or the proposed build.
2. Select supported React/TypeScript/build versions against those packages.
   Atlassian's current setup recommends Parcel and supports Webpack; its Vite
   integration is experimental. Select based on reviewed compatibility, not an
   automatic scaffold. Source links and preliminary metadata are in
   codebase-analysis-docs/assets/BROWSER_REACT_ADS_DECISION.md.
3. After approval, create a bounded browser workspace (proposed `browser/`), its
   own explicit build/dependency lock and source/notice inventory. Keep the root
   package lock and production Telegram asset pipeline stable. Decide integration
   with Django static assets in a small, rehearsed build change; no separate
   hosting service is implied by a separate framework.
4. A source-only synthetic wireframe may review these states before installation
   (ADR 0062 clarification, BROWSER_REACT_ADS_DECISION.md section 6). It uses no
   vendor assets, credentials or APIs and does not satisfy the React build gate.
   After acceptance, build only company login, MFA/enrollment/recovery states and a signed-in shell
   initially. Use reviewed ADS tokens/components, required style transforms and
   lint rules; use company branding/system fonts until other assets are cleared.
   ADS adoption does not automatically prove accessibility or compliance.
5. Extend the UI review process for these browser components before UI work:
   reviewed source/version mapping, keyboard/focus/error/loading/mobile behavior,
   real browser evidence, and isolation from Telegram. Existing Design Lab
   candidates do not authorize Telegram restyling.
6. Test real React → CSRF/session → Django password/MFA → denied/allowed owning
   workflow context, including rotated CSRF, expiry/revocation, stale bundles,
   network failure and absence of Telegram. No business permissions arise from
   the signed-in shell. Finish scoped M1 staging/support acceptance before P2.

P1c.1 now completes the exact local build/component scope above, with synthetic
access pages and source review. Native API/CSRF/session transport, deployment
static/CSP/cache integration and operational M1 were unimplemented/unaccepted.
P1c.5 implements native sign-in under ADR 0067. P1c.6 connects the guided
initial-password, QR enrollment and one-time recovery UI under ADR 0068
(decision section 12). Actual delivery/support, production static/CSP/origin/
cache, PostgreSQL/device and M0/M1 acceptance remain open. Local guided UI
is not operational onboarding acceptance.
P1b.2b and P1c continue in bounded increments under their own gates; local build
acceptance never relaxes authentication or approves an unreviewed graph. No
calendar promises or traffic percentages are inferred.

Work:

- Implement controlled provisioning of existing Django users, password/TOTP/recovery assurance, logout, factor reset, local session revocation and audit. Callback/issuer/audience checks apply only to a future separately added external provider.
- Keep browser routes and cohorts disabled by default. A Telegram-issued session alone must not silently qualify as company-authenticated browser access.
- Supply real current workflow access contexts; no production None/local-auth bypass.
- Add schema only if required, in a bounded domain with catalogue metadata and a reviewed migration/reversal/compatibility plan. No employee/case primary-key replacement or mass account conversion.
- Implement independently enforceable browser admission/surface/write controls; document what happens to queued/in-flight work and prepared capabilities.
- Add readiness checks for enabled browser access while preserving off-mode and all existing Telegram auth gates.
- Prove provider failure affects company login safely without breaking existing Telegram access.
- Complete the relevant staging/test setup and review work budgeted at M0.

**M1 exit:** actual provisioned password/MFA login resolves the intended existing staff account in staging; password-only, unenrolled, inactive, replayed, revoked, cross-account and credential-confused requests are denied; recovery/helpdesk/audit, shared-cache controls, transient-secret storage, Telegram scripted regression and applicable PostgreSQL/schema rollback checks pass. These remain required demonstrations, not a claim from P1a tests. External issuer/audience checks apply only if a provider is subsequently commissioned.

**Rollback:** leave browser admission off, preserve legitimate link/audit evidence, and avoid unrelated Telegram account changes.

### P2 — Complaints read pilot

**Operational entry:** M1 accepted, named Complaints audience and privacy-reviewed display projection.

**P2a development exception (20 October 2026):** the user agreed to start
isolated Complaints integration now. ADR 0070 permits the separate dormant
read client/API and native end-to-end synthetic tests alongside M1 work.
This does not admit real staff, accept a privacy projection or satisfy M2.
The initial projection excludes identifiers, raw messages, evidence/location,
sync diagnostics and history notes/diffs; names/descriptions still require
human privacy review. Browser search uses names/references only. Existing
read-side control/reference initialization and daily capability usage remain;
case state, history and external publication are not changed by these reads.

Work:

- Start with authorized complaint list, search, paging, selected detail and history.
- Reuse core/services/complaint_cases.py::staff_actor_for_user, list_cases_page and case_detail with the existing policy services; keep the Telegram _context boundary intact.
- Do not expose a complete case_detail payload just because it exists: it includes raw message, evidence/location and other sensitive fields. Allowlist the browser pilot's approved fields and defer unreviewed media/export.
- Preserve the actual Complaint group/branch scope. No authority is inferred from Portal/TAT/Origination grants.
- Source clarification from P0: Complaint reads are intentionally shared across branches inside one authorized group. Preserve that policy; do not treat every other-branch read as unauthorized. Review scope per action rather than inventing a universal branch filter.
- Implement the browser Complaint screens in the reviewed React/ADS workspace. Reuse workflow meaning and shared backend services, not Telegram templates/SDK or their credential transport. Telegram screens remain intact; the browser works with Telegram hosts blocked.
- Audit read-side initialization/access-history effects explicitly; “read pilot” means no operational complaint edits, not an unsupported promise of zero database writes.
- Run actual company-login → Django → isolated data end-to-end tests. Mock APIs and force_login unit tests do not prove this complete boundary.

**M2 exit:** named reviewers pass the scripted read/denial/revocation/cache/network journeys in both channels and accept the exposed fields. A small optional production read cohort requires separate release approval and human review of observed usage; zero traffic is not evidence.

**Review:** if read access meets D2, stop here. P3 requires a business need for a write and an approved D5.

### P3 — Complaints bounded write and mandatory investment review

**Proposed first write:** an append-only resolution comment on an existing open complaint, using the existing complaint.case.comment authority. D5 confirms whether this is appropriate; creation, resolution, reopening, evidence upload and import are not silently included.

Source facts, not runtime guarantees: core/services/complaint_cases.py::comment_case checks the actor, request key, payload hash, expected revision and open status; locks records; writes a CaseUpdate/event/compliance record; **increments the control revision**; and may attempt Sheet publication after commit. It does not close the complaint. That publication dependency and the normal reporting consequences must be accepted, not described as a side-effect-free note.

Work:

- Add a separate CSRF-protected browser comment endpoint calling comment_case, not the exempt Telegram HTTP view.
- Preserve actor, scope, reason/text validation, closed-case denial, retry conflict, revision and existing audit/business-source values.
- Test browser and Telegram racing on the same complaint, duplicate/changed-payload requests, lost responses and subsequent case changes.
- Test Sheet unavailability: show the difference between a saved canonical comment and failed/pending publication; do not invite another comment submission just because projection failed.
- Do not enable optional voice/media handling in the first write without its own manifest and tests.
- Rehearse browser-only containment with the backup maintainer, including direct bookmarked APIs and admitted/uncertain work.
- Use staged synthetic comments; production observations must be legitimate approved staff activity, never invented customer feedback.

**M3 technical exit:** scripted permitted/denied/race/retry/audit/CSRF/publication-failure journeys pass; real ordinary-role acceptance and a usable operator procedure exist; Telegram remains working.

**M3 business review — required before P4:**

1. Did browser access deliver D2's expected benefit to D3's users?
2. What was the actual time spent on coding, governance, QA, support and review?
3. Were there incidents, extra helpdesk burden or unresolved privacy risks?
4. Can the backup maintainer operate/recover it without the author?
5. Which Telegram dependencies remain, and are they acceptable for the chosen driver?
6. Does JBL approve keeping the limited Complaints pilot, further Complaint coverage, the next TAT pilot, or stopping?

A passed technical demo does not approve TAT, Origination or Portal. Scope, capacity and estimates are renewed before each application.

### P4 — TAT pilot, second application

**Entry:** explicit M3 decision to proceed, TAT owner and scoped requirements. No calendar commitment yet.

Start with queue/search/case facts and the current authorized inbox. A candidate first write is the existing append-only TAT remark, if confirmed useful and independently authorized. Stage progression, routing configuration, approvals and notification redesign are separate later increments.

Sources: core/api/views.py::_tat_context, core/services/tat_tracker.py, core/services/tat_notifications.py and the existing remark implementation/ADR 0051. Read the exact current remark path before committing its adapter contract.

Preserve configuration binding, frozen loan-cycle paths, Pilot/Production mode, stage timing/revisions, recognition facts, task responsibilities and the remark's special non-transition semantics. TAT roles do not transfer to Origination or other Mini Apps.

Private connection status and backup/escalation can be Telegram-shaped. For convenience-only scope, record those limitations. For a continuity claim, demonstrate independent task discovery/delivery and acceptable escalation behavior before acceptance; a readable case screen alone is insufficient.

**M4 exit:** accepted scoped TAT read/write behavior, no unintended stage/task/routing change, both-channel regression, maintenance handoff and a renewed investment decision before Origination.

### P5 — Origination pilot, third application

**Entry:** M4 review approves the next bounded scope; Origination owner and security reviewer available. Estimate this app separately.

Start with authorized application list/detail and approved preview access. Choose a low-risk draft action only after reviewing its actual policy adoption, revisions and side effects. Do not treat draft edits as automatically harmless.

Keep origination/auth.py Telegram behavior, independent Origination grants, captured product/document versions, approval/completion policies, consent, signer identities, revisions and retained PDF/signature bytes. Staff company login is not applicant consent or a signature. Public signer/OTP credentials remain separate.

Dispatching links/OTP/SMS, submission, signing, approval, document changes and Daraja paid checks are excluded until separately scoped and accepted. No mount, refresh, login or poll may generate an unintended message or billable request. Preserve existing provider-bound delivery evidence and retrieval-time authorization.

**M5 exit:** the agreed Origination pilot and negative/recovery paths pass without reinterpreting historical applications. Document exclusions and support burden, then decide whether to commission Portal.

### P6 — Portal pilot, fourth application

**Entry:** M5 review approves Portal and its audience. No Portal-first exception is implied by code being reusable.

Start with scoped case list/search and selected history. Defer broad finance, exports and media disclosure. The first write candidate is **HB Deposits**, through hb_operations/deposits.py::update_deposit, after its own acceptance brief.

Preserve cumulative Decimal amounts, the KES 5,000 first-visit gate, reason-for-reduction, first-visit edit lock, HB source ownership, complete Portal scope, existing revision/retry/audit and publication reservation. Operations remains read-only, scoped HB retains its authority and technical exceptions remain as currently governed.

Concurrent saves from either client use one canonical record; neither interface bypasses the held JBL queue. Current source/policy references include hb_operations/deposit_views.py and codebase-analysis-docs/assets/HB_DEPOSITS.md.

FarmUp intake, JBL/credit/final decisions, invoice identity, official orders, payment review, evidence/signing and installation/commissioning are **subsequent optional Portal packages**, not part of a blanket Portal pilot. They retain exact-workspace finality, finance-number governance and chronology. New orders remain oldest-first; new payments retain partner-first chronology; historical retained documents are not regenerated.

**M6 exit:** the exact accepted Portal read/write scope works in both channels; finance/evidence/routing exclusions are explicit; support/rollback are rehearsed. Do not label the entire Portal browser-ready based on a deposit demo.

### P7 — Continuity/exit proof only when required by D2

This is not an automatic final phase for a browser-convenience project.

For the agreed operational scenario, block Telegram API, SDK, launchers and message input **in staging** and prove:

- New staff enrollment/recovery and current authority without a Telegram account.
- New case intake, not just existing-record search.
- Authorized work discovery, updates and required notifications/escalation.
- Required evidence retrieval/signing paths and audit.
- Sheet/Drive and other owned integration processing without a hidden visible Telegram client.
- Helpdesk, session offboarding, recovery and operator handover.

Also test company IdP outage while existing Telegram remains functional. Identify what remains dependent on Google, hosting and other providers. Do not equate Telegram independence with eliminating every provider.

**M7 exit:** owners accept the precise continuity scope, residual risks and measured recovery evidence. Telegram retirement requires a separate business/decommission decision. It is not authorized by any pilot milestone.

**Findings:** the sequence is Complaints, TAT, Origination, Portal, each gated and narrow. **Open questions:** exact later write choices and business value. **Next steps:** only estimate the next application after accepting the previous one.

## 7. Hidden dependencies and early privacy gates

| Dependency | Discovery requirement | Acceptance consequence |
|---|---|---|
| Sheet publication/client activity | Determine who advances each pilot's failed/pending work and whether a visible client is required | No false saved/failed message; continuity needs independent progress |
| Group IDs as business scope | Record existing authorized configurations and link generation | Reuse current scope; do not remove group identifiers as a login refactor |
| Telegram-shaped intake | Identify active message/file/import/command entry points | Convenience may exclude them; continuity/exit cannot |
| Staff activation/recovery | Separate granting workflow authority from binding a Telegram account | New browser-only employee proof when continuity is required |
| TAT tasks/private connectivity | Review inbox, recipient eligibility, escalation and delivery dependence | Defer routing changes or explicitly accept their separate policy scope |
| Evidence and signing | Inventory raw messages, document capabilities, recipient identity and retained bytes | Privacy field allowlist and current retrieval checks precede exposure |
| Monitoring/backups/providers | Map actual processors, storage, retention, transfers and account ownership | Privacy owner reviews real flows, not architecture diagrams alone |

Early data-flow screening applies to every driver. Where compliance is the primary reason, a qualified review determines the scope and whether a new browser channel is an appropriate response before P1/P2. Do not defer material privacy findings to P7 or mistake this Markdown for a legal assessment. [R7]

Runbooks must name the person who owns each pending integration/recovery path. A browser screen being functional does not mean the company can operate without Telegram.

**Findings:** hidden dependencies determine what can honestly be promised. **Open questions:** actual deployed processors, configuration and scope. **Next steps:** record blockers/exclusions in P0 and revisit each application gate.

## 8. Small-cohort acceptance: scripts and human review

There are **no invented numeric operational thresholds** in this revision. No percentage, percentile, time-to-contain or fixed event-count rule can establish safety from a handful of pilot users.

### 8.1 Admission and observation

Start with the smallest representative set of already authorized Complaints readers; add the approved comment role only for P3. Do not broaden roles or create fake production activity to meet a cohort count.

Agree a review point with the business/IT owners, cover the named journeys, inspect outcomes and collect staff feedback. Low usage requires staged scripted coverage and/or more observation, not an automatic pass after a fixed number of days. Observation dates and scenarios are recorded, not treated as statistically meaningful traffic volumes.

Each new app starts restricted again. Its users and grants are resolved within that app; an existing browser session supplies no inherited business authority.

### 8.2 Mandatory journeys and reviewer decision

| Area | Required scripted/reviewed proof | Stop or contain if |
|---|---|---|
| Company login/session | Correct existing user, ordinary staff role, safe callback, logout/recovery and session revocation | Wrong identity, unsafe fallback or usable revoked authority |
| Credential/CSRF boundary | Cookie-only request cannot enter old Telegram write; new browser write requires valid CSRF/assurance | Any bypass, confused actor or broadened scope |
| Authorization | Allowed role succeeds; requests outside the owning action's actual scope fail. Complaint queue reads remain shared within the authorized group | Any unauthorized data/action or unapproved scope-policy change |
| Telegram compatibility | Current critical journey works before/after; shared assets and stale WebViews tested | Existing legitimate usage breaks or unexpectedly requires company login |
| Write/audit parity | One canonical allowed effect, correct actor, current revision, preserved evidence | Missing required audit, wrong state, duplicate effect or financial/signing anomaly |
| Retry/concurrency | Duplicate/changed payload, stale form, lost response and competing channel tested | Silent overwrite or duplicate action; uncertain state cannot be reconciled |
| Publication/routing | Canonical save and projection/delivery outcomes are distinguishable and recoverable | Duplicate disclosure, unexplained pending work or changed escalation |
| Usability/performance | Reviewer completes representative flows on supported devices and inspects comparable timings/logs | Reproducible unusable delay, resource exhaustion, errors or unexplained regression |
| Support/containment | Named backup disables affected browser surface and reconciles an in-flight case | Procedure cannot be executed or disrupts unrelated Telegram activity |

All mandatory acceptance journeys must pass or remain an explicit blocking gap. Human review considers severity, reproducibility and actual operating consequences; it does not waive authorization, audit or financial-integrity failures.

Record actual containment steps, elapsed time, control propagation and in-flight behavior in rehearsal. Set a response objective later only if operations can support it. A settings flag requiring redeployment is not an instantaneous kill switch.

Collect privacy-safe baseline observations when available. Do not claim service-level success from near-zero traffic. If larger volumes later justify statistical monitoring, propose metrics and thresholds from actual data in a separate reviewed operational decision.

Use only reviewed safe metadata. Do not log raw initData, cookies, provider tokens, customer searches, private evidence or identity lists. Sentry's existing minimization policy is not permission to add sensitive monitoring.

**Findings:** use deterministic scenarios and accountable review, not tiny-sample percentages. **Open questions:** reviewer availability and actual observations. **Next steps:** approve the Complaints scripts before production admission.

## 9. Release, migration and rollback without data loss

Follow the existing release process rather than creating a second one: release.sh, core/management/commands/release_production.py, core/services/production_release.py, docs/production-release-record.md and PRODUCTION_RUNBOOK.md. Completed production evidence remains in approved private storage, not Git.

### Before each release

1. Obtain explicit approval for the actual dependency, access, migration, production or financial action where required. A plan or green CI is not deployment authority.
2. Record known deployed state, open issues, exact commit, affected workflow, migration plan and compatible known-good application.
3. Run focused tests first, then required broad/CI/governance/PostgreSQL/UI and both-channel checks. Keep full-suite failures visible with an owner and release decision; do not claim subset success as a waiver.
4. For schema changes, rehearse old-app/new-schema compatibility, locks and relevant worker overlap. Record exact real migration names/reversal and forward repair. No invented migration number is supplied here.
5. Keep the browser closed for deployment. Verify Telegram first, then admit only the accepted browser surface/cohort after its separate go decision.
6. Keep operator and backup available for actual usage review. Do not overlap unrelated shared-policy/schema releases.

Render's deployment process does not remove application/schema/in-flight risks; actual service configuration and any deployment exceptions must be inspected. No promise of zero downtime or a measured rollback duration follows from vendor documentation. [R5]

### Rollback rules

| Failure class | Action | Preserve |
|---|---|---|
| Browser-only UI/function fault | Close that surface/new browser writes | Telegram use and all committed records |
| IdP/company-session fault | Hold company login or revoke affected browser sessions | Unrelated valid Telegram identities and grants |
| Browser authorization/privacy incident | Contain affected reads/writes and related disclosure, follow incident procedure | Audit and evidence; investigate queued/in-flight work |
| Shared asset/backend Telegram regression | Close browser; use compatible known-good app or reviewed forward fix | Existing business state; a browser switch alone does not repair shared code |
| Schema/data-integrity fault | Authorized writer containment and reviewed forward correction | Accepted events, signatures, finance claims and integration evidence |
| Disaster requiring restore | Existing incident authority, exact backup and accepted data-loss window | No routine database restore to undo a browser feature |

A timed-out save may have committed. Keep its retry/reference, inspect current authorized state and reconcile before re-entering in Telegram with a new key. Do not duplicate writes for shadow tests or add channel labels to business deduplication keys.

Contain new admissions without splitting an admitted transaction. Review prepared capabilities and queued owned work separately; disabling navigation does not revoke every credential or cancel a remote dispatch. Do not erase a valid comment, deposit, signature or audit event during application rollback.

Additive identity schema can remain during rollback. Destructive contraction, user-ID changes, bulk historical backfills and Telegram decommissioning are excluded. Schema changes require the exact implementation-specific reversal/compatibility evidence before release.

**Findings:** browser rollback must not discard successful Telegram or browser work. **Open questions:** actual migration and worker topology per package. **Next steps:** rehearse the affected paths and record facts, not guessed response times.

## 10. Test strategy and source starting points

This remains the programme acceptance strategy, not a claim that every row has
passed. P1a's narrower executed results (53 focused application tests and 28
governance script tests) and wider check failures are recorded in
codebase-analysis-docs/assets/STAFF_BROWSER_MFA_FOUNDATION.md.

| Layer | Required work | Starting sources |
|---|---|---|
| Authentication/session | Existing-user provisioning, password/MFA assurance, CSRF, account recovery and already-open-session revocation; provider callbacks only for a future external provider | core/tests_telegram_authentication.py, core/tests_user_identity.py, staff_auth/tests.py, staff_auth/tests_browser_api.py |
| Complaints read/write | Field allowlist, exact scope, closed case, revision, retry/payload, actor audit and Sheet failure | core/tests_complaint_cases.py, core/tests_complaint_timing.py, core/services/complaint_cases.py |
| Complaint browser UI | New reviewed React renderer/transport, absent Telegram, forbidden role and retained input; existing Telegram UI remains a parity boundary | New React test suite is planned, not created; core/tests_browser/complaint_comments.spec.js and existing Complaint tests remain legacy parity evidence |
| Shared assets | Telegram and browser behavior for every runtime/transport/template change; stale client/server combinations | core/static/miniapp/utils.js, core/static/miniapp/complaint_cases_api.js, owning assets |
| PostgreSQL/release | Applicable real locks/races/migrations and old/new workers, not SQLite-only conclusions | .github/workflows/ci.yml, core/tests_release_sequencing.py |
| Actual end-to-end | Approved provider → actual Django → isolated data; no mock API as the only proof | New isolated pilot journeys/staging |
| Later apps | Their own roles, timing/tasks, snapshots/signing, financial evidence and recovery | Owning tests; no blanket extension of Complaint acceptance |

Read docs/ui-standard/README.md and docs/ui-standard/component-index.md before interaction/appearance edits. Preserve source ratchet, candidate review and human approval; do not update baselines to make CI pass. Real-device Telegram/browser evidence remains separate from headless screenshots.

Production/customer data, credentials and real external side effects remain excluded from default tests. Use synthetic fixtures and blocked/mocked transports. Real provider/staff operational checks require their own authority.

**Findings:** source presence points to where tests belong; only execution establishes results. **Open questions:** current failures, devices and staging access. **Next steps:** capture the actual P0 baseline and budget missing fixtures/rehearsals.

## 11. Minimal work packages and review checkpoints

| Package | Scope | Decision to proceed |
|---|---|---|
| WP01 | Timeboxed D1–D3 discovery, endpoint baseline, privacy/support screening | M0 go/hold/no-go |
| WP02 | Approved identity/provider/session and optional additive schema | M1 staging acceptance |
| WP03 | Complaint read projection, separate browser endpoint and UI adapter | M2 reviewer acceptance |
| WP04 | One justified Complaint write, concurrency, publication and rollback | M3 technical and business review |
| WP05 | TAT pilot only | Separately approved scope/estimate after M3 |
| WP06 | Origination pilot only | Separately approved scope/estimate after M4 |
| WP07 | Portal pilot only; possible deposit write | Separately approved scope/estimate after M5 |
| WP08 | Driver-specific continuity gaps and drill | Only if D2 requires it; acceptance for exact scope |

Each package may need several small PRs. Separate structural/access decisions from business-rule changes; do not turn the sequence into one architecture branch. Reuse existing evidence/release records and budget their preparation/review. Later workflow functionality is not a free addition to its pilot.

P0 closing brief:

- D1: selected Django/allauth TOTP/recovery, with provisioning/recovery ownership and remaining operational obligations.
- D2: selected browser convenience with possible future exit; accepted benefit and scope exclusions.
- D3: existing Django Complaints grants; identify exact pilot accounts without changing scope policy.
- Source versus actual test/deployment observations; known gaps.
- Privacy findings and qualified-review actions where needed.
- Primary/backup maintainer and support capacity.
- Pilot endpoint manifest, separate coding/governance/test/support estimates.
- Decision: proceed with P1/P2, narrow, obtain missing prerequisites or stop.

The initial decision is not a request to approve all future apps. M3 explicitly renews the business case before any TAT/Origination/Portal commitment.

**Findings:** the current tranche is a dormant foundation, not user admission.
**Open questions:** operational owners and release/support acceptance above.
**Next steps:** P1b operational identity controls, then M1 review.

## 12. Scope limits and current status

Excluded unless separately commissioned: Telegram React/SPA rewrite, microservices, second business database, native mobile/offline sync, provider/storage migration, global roles/customer identity joins, TAT stage redesign, Origination policy/signature changes, broad Portal finance, automatic paid API retries and Telegram retirement. The selected new browser React frontend is in scope, but package installation is gated by D13.

| Item | Status |
|---|---|
| Required pilot sequence | User specified: Complaints → TAT → Origination → Portal |
| D1–D3 | User selected Django/allauth MFA, browser convenience with possible later exit, existing Django Complaints grants |
| D13a | Exact-graph review slice; no frontend installation or dependency approval. Current evidence/limits/checklist in BROWSER_REACT_ADS_DECISION.md section 5 |
| P0–P7/M0–M7 | P1a/P1b.1/P1b.2a/P1b.2b.1/P1b.2b.2/P1b.2b.3 dormant backend slices; browser closed, operational M0/M1 and later milestones not accepted |
| Source investigation | Read-only source inspection; code findings are not runtime verification |
| Revision 9 | Closed existing-staff initial setup; scope/schema/verification/checklist in STAFF_BROWSER_INITIAL_SETUP.md; real delivery/support, native shared rate-cache and P1c/M1 gates remain open; no frontend installation or production activation |
| Revision 10 | Local source-only access wireframe and synthetic browser evidence; BROWSER_REACT_ADS_DECISION.md section 6; historical no-install state |
| Revision 11 | Actual local React/ADS access demo, exact dependency/build decision, notices/module checks and browser evidence; section 7; synthetic frontend foundation only |
| Revision 15 | Separate dormant native session/password/MFA/logout client, short sign-in and isolated React/Django integration under ADR 0067; decision section 11. Guided initial setup/enrollment/recovery UI, production distribution and M0/M1 remain open |

| This revision (16) | Guided existing-account native first-password/QR enrollment/one-time recovery UI under ADR 0068; decision section 12. Local onboarding UI gap closed; delivery/support and M0/M1 remain open |

### STATE BLOCK - revision 16 / P1c.6 guided closed onboarding

- INDEX_VERSION: platform-independence-plan-16 / 20 October 2026; ADR 0068.
- FILE_MAP_SUMMARY: dormant React auth sources; bound-session setup/enrollment
  progress and native QR; native/regression tests; candidate bindings and docs.
- OPEN_QUESTIONS: actual invitation delivery/verified support, shared cache/privacy/
  PostgreSQL, production static/origin/CSP, devices/assistive, named support/backup
  and M0/M1 staging acceptance.
- KNOWN_RISKS: closed integration is not operational admission or workflow access;
  lost one-time recovery disclosure needs verified support.
- GLOSSARY_DELTA: React client definition extended for guided native setup.
- VERIFICATION: 59-case backend run (54 passed/five PostgreSQL-only skips); final
  10 progress/transport tests passed with 39 native checks/17 masked captures per
  build. Exact source bindings, limits and rollback: decision section 12/checklist.
- NEXT_READ_QUEUE: readiness/staging acceptance for M1, then Complaints read;
  mandatory M3 review before TAT/Origination/Portal investment.

### STATE BLOCK — revision 15 / P1c.5 closed native sign-in

- INDEX_VERSION: platform-independence-plan-15 / 20 October 2026; ADR 0067.
  Prior demo/identity slices remain; no operational admission or deployment.
- FILE_MAP_SUMMARY: separate browser auth entry/transport; owned stale-session
  restart and denial regressions; isolated test URLconf/settings/runner/native
  browser script; CI and source-bound review/docs/checklist.
- OPEN_QUESTIONS: short guided initial setup/enrollment/recovery handoff and
  actual delivery/support, native shared cache/privacy/PostgreSQL, origin/static/
  CSP, device/assistive/backup/staging and M0/M1 acceptance.
- KNOWN_RISKS: real native authentication in synthetic tests is not a production
  login product or workflow authority. The fixed-value preview stays disconnected.
- GLOSSARY_DELTA: existing React browser client updated; no new business term.
- VERIFICATION: affected staff_auth suite 139 passed/nine PostgreSQL-only skips;
  final five transport tests pass, with 25 native checks/10 proof-free captures
  per build mode. Exact scope, source bindings and remaining gates are recorded
  in decision section 11 and the current release checklist.
- NEXT_READ_QUEUE: guided setup/enrollment/recovery UI and identity/support gates;
  M1 before Complaints, mandatory M3 before TAT/Origination/Portal investment.

### STATE BLOCK — revision 6 / D13a dependency review

- INDEX_VERSION: platform-independence-plan-6; original source investigation baseline retained above; current D13a starts from clean f7b23a51. No commit, merge or deployment by this phase; deployed release/migrations unknown.
- FILE_MAP_SUMMARY: staff_auth JSON/assurance/admission/session protection and tests; config/settings.py; ADRs 0060–0062; browser React/ADS decision and licence shortlist; Complaint actor/list/detail/comment and release/UI governance. TAT/Origination/Portal remain later owners.
- OPEN_QUESTIONS: D13 exact transitive/asset licences/build, provisioning/recovery/mail/cache controls and owners, pilot accounts, privacy/support owners, deployed baseline and two-frontend maintenance capacity. D1–D3 answered by user.
- KNOWN_RISKS: licence assumptions, shared-cache replay, CSRF/session fallback, production access=None, cross-workflow grants, stale assets, revocation, hidden intake/onboarding/integration dependencies and single-maintainer burden.
- GLOSSARY_DELTA: company browser boundary requires channel/audit receipt plus MFA assurance, never grants; separate React client does not imply Telegram UI migration or legal/compliance clearance.
- NEXT_READ_QUEUE: resolve/accept D13a exact-graph licence/asset/build findings before frontend installation; independently scoped P1b.2b provisioning/enrollment/recovery/shared cache/support; P1c reviewed browser foundation; M1 staging acceptance before Complaints. No production mutation based solely on this plan.
- VERIFICATION: historical auth-phase evidence remains in its phase documents. D13a inspected all 529 unique archives / 546 entries, with zero remaining errors; final 44 governance/tool tests and offline snapshot binding passed. Original-peer/licence/asset/build acceptance remains open. No application-suite rerun, installation, production inspection or activation in this review-only slice.

**Findings:** user decisions now allow bounded local self-managed identity work; operational admission is not ready. **Open questions:** release/support evidence and P1b controls. **Next steps:** complete P1b/M1 before the Complaints pilot; retain the M3 review.

### STATE BLOCK — revision 7 / P1b.2b.1 closed enrollment

- INDEX_VERSION: platform-independence-plan-7; this slice starts at clean `144ed843` on Platform-Interdependence. No merge/deployment/production inspection; actual release/migrations unknown.
- FILE_MAP_SUMMARY: staff_auth/enrollment.py, enrollment_state.py, browser_api.py, browser_urls.py, session_protection.py, tests_enrollment.py; existing assurance/lifecycle/signals; ADR 0063; STAFF_BROWSER_ENROLLMENT.md; release checklist.
- OPEN_QUESTIONS: controlled provisioning, support/recovery, shared native replay cache, notifications, deployed baseline, backup maintainer, D13 peer/licence/asset/build acceptance and M1.
- KNOWN_RISKS: interrupted setup/uncertain code disclosure, stale sessions/admission, shared-cache replay, new callback receivers, unexecuted PostgreSQL races, Telegram regression and premature mounting. No operational admission authorized.
- GLOSSARY_DELTA: closed enrollment/one-time recovery handoff are setup only; fresh subsequent password/MFA login remains mandatory and supplies no workflow grants.
- NEXT_READ_QUEUE: bounded provisioning/recovery/cache controls; resolve exact ADS graph/review; approved client; M1 staging/support acceptance; Complaints; M3 review before TAT/Origination/Portal investment.
- VERIFICATION: current executed results and remaining limits are maintained in STAFF_BROWSER_ENROLLMENT.md section 5; previous D13a counts remain historical above.

**Decisions/Findings:** progress the closed backend without weakening frontend or
release gates. **Open Questions:** operational acceptance remains open.
**Next Steps:** one bounded prerequisite, not production admission.

### STATE BLOCK — revision 8 / P1b.2b.2 shared browser TOTP use

- INDEX_VERSION: platform-independence-plan-8; starts at `bb232703` on Platform-Interdependence. Existing pinned local allauth dependency restored. No merge/deployment/production inspection; actual release/migrations unknown.
- FILE_MAP_SUMMARY: staff_auth/replay.py; browser_api.py; StaffTOTPReplayState and migration 0002; catalogue/admin; purge_staff_totp_replays; tests_replay.py; ADR 0064; STAFF_BROWSER_REPLAY_GUARD.md; release checklist/catalogue.
- OPEN_QUESTIONS: controlled existing-staff provisioning/password/address, recovery/support, native shared rate-limit cache, notifications, PostgreSQL and actual worker/cache evidence, deployed baseline, cleanup/backup owners, D13 and M1.
- KNOWN_RISKS: native normalization changes, live-claim eviction/schema reversal, uncertain login after code use, cache topology and premature alternate mounts. No operational admission authorized.
- GLOSSARY_DELTA: browser TOTP use claim reserves successful native code use across independent caches. It is not a verifier, login receipt, MFA assurance or workflow grant.
- NEXT_READ_QUEUE: another bounded P1b prerequisite; resolve exact ADS graph; P1c; M1 before Complaints; M3 review before TAT/Origination/Portal investment.
- VERIFICATION: current executed results and limits are maintained in STAFF_BROWSER_REPLAY_GUARD.md section 4; earlier phase counts remain historical.

### STATE BLOCK — revision 11 / actual React/ADS local client

- INDEX_VERSION: platform-independence-plan-11 / P1c.1 / 20 October 2026; source start `1b07b549`, branch ahead two plus prior uncommitted wireframe. Production state unknown; no commit/merge/deploy performed.
- FILE_MAP_SUMMARY: browser workspace/source/build/notice/review; ADR 0066; hashed loopback server; actual browser and boundary tests; TSX source ratchet/component inventory; isolated CI job; release checklist.
- OPEN_QUESTIONS: native backend transport, distribution/static/CSP/cache integration, human/device/assistive review, proof delivery/recovery, shared cache/privacy, PostgreSQL, support/backup owners and M0/M1.
- KNOWN_RISKS: one explicit upstream React-peer exception, selector override/tool maintenance, deprecated vendor transitives and synthetic success mistaken for business authority. Browser auth off/E006/routes retained.
- GLOSSARY_DELTA: installed React/ADS client is an actual local component build, currently fixed-demo and disconnected; local dependency decision is not production admission.
- NEXT_READ_QUEUE: bounded native CSRF/session integration and remaining backend/support controls; M1 before Complaints; M3 review before TAT/Origination/Portal.
- VERIFICATION: 79 production-browser checks/71 synthetic captures, exact original-peer/context/parser/type/lint/build checks and point-in-time zero-vulnerability audit pass. Final tooling/static counts and limits are in decision section 7 and release handoff; no operational certification.

### STATE BLOCK — revision 10 / source-only access preview

- INDEX_VERSION: platform-independence-plan-10 / 20 October 2026; source start `1b07b549`, clean branch ahead two. Production release/migrations unknown; no merge/deploy by this phase.
- FILE_MAP_SUMMARY: browser-access-preview/{index.html,preview.css,preview.js}; loopback server; focused Python/server and existing-Playwright browser checks; UI candidate registry/index; ADR 0062 clarification; React decision section 6; release checklist.
- OPEN_QUESTIONS: D13 exact peer/licence/asset/notice/build acceptance, supported Node, real React client, native cache/log privacy, proof delivery/interrupted setup/recovery, PostgreSQL, support owners and M0/M1.
- KNOWN_RISKS: synthetic navigation/screenshots mistaken for real authentication or approval. Preview is loopback/fixed-assets only; browser auth off, E006 blocking and production routes unmounted.
- GLOSSARY_DELTA: browser access preview is an analysis artifact with fixed demo values, not an operational client or account/session.
- NEXT_READ_QUEUE: review preview and resolve/accept D13 before the real React/ADS auth implementation; finish remaining backend/support/M1 controls before Complaints; retain M3 investment review and later pilot order.
- VERIFICATION: 78 browser checks, 70 synthetic screenshots and all 50 tooling/governance tests passed; current source hashes match capture/registry records. Narrow lint, source/UI/dependency/route/database checks passed; details and limits are in BROWSER_REACT_ADS_DECISION.md section 6. No Django auth/PostgreSQL/real device/provider/production certification is added by the wireframe.

### STATE BLOCK — revision 9 / P1b.2b.3 closed existing-staff initial setup

- INDEX_VERSION: platform-independence-plan-9; starts at `3d2ffdfb` on Platform-Interdependence. No merge/deployment/production inspection; actual release/migrations unknown.
- FILE_MAP_SUMMARY: initial_setup.py; setup_api.py; setup model/metadata/admin/migration 0003; prepare/purge commands; session protection; tests_initial_setup.py; ADR 0065; STAFF_BROWSER_INITIAL_SETUP.md; plan/checklist/catalogue/glossary.
- OPEN_QUESTIONS: actual proof delivery/support, usable-password address verification/recovery, shared native cache/log privacy, notifications, PostgreSQL, deployed baseline, cleanup/backup owners, D13/frontend and M1.
- KNOWN_RISKS: proof delivery/session loss, callbacks/native upgrades, shared session-hash effects, unsafe schema rollback/live-state cleanup and premature mounts. No operational admission authorized.
- GLOSSARY_DELTA: closed staff initial setup prepares and verifies the exact existing unusable-password account; it never creates identity, resets usable credentials or grants login/MFA/workflow authority.
- NEXT_READ_QUEUE: controlled delivery/support or native shared cache/privacy prerequisite; exact frontend acceptance/P1c; M1 before Complaints; M3 before later application investment.
- VERIFICATION: current executed results/limits are maintained in STAFF_BROWSER_INITIAL_SETUP.md section 6; earlier phase counts remain historical.

### STATE BLOCK - revision 17 / P1b.2b.4 closed abuse boundary

- INDEX_VERSION: platform-independence-plan-17; starts at `d74c72c9`. Production
  release/migrations remain uninspected; no merge, deployment or real staff action.
- FILE_MAP_SUMMARY: abuse.py, cache_keys.py, checks.py, browser/setup/enrollment
  handlers, tests_abuse.py, native harness bindings, ADR 0069 and current checklist.
- OPEN_QUESTIONS: approved shared cache/service/client/topology, real delivery and
  verified support, PostgreSQL/workers, production origin/static/CSP, devices and M0/M1.
- KNOWN_RISKS: premature mounting, untrusted proxy configuration, early eviction,
  cache/key rotation with live state, and unavailable session cleanup storage.
- GLOSSARY_DELTA: native IP policy and cache privacy strengthen the existing
  browser boundary; neither grants workflow authority or shared-cache acceptance.
- NEXT_READ_QUEUE: controlled invitation delivery/support and deployment-ready
  cache/worker evidence; M1 staging acceptance before Complaints. Preserve the
  later TAT, Origination, Portal order and M3 investment review.
- VERIFICATION: executed results and explicit not-run gates live in the current
  release checklist; historical frontend/backend counts remain phase-specific.

### STATE BLOCK - revision 18 / P2a closed Complaints reads

- INDEX_VERSION: platform-independence-plan-18; starts at `7ceac557`. Production
  state remains uninspected; no merge, deployment or real staff admission.
- FILE_MAP_SUMMARY: separate Complaints React entry/transport/workspace/build;
  dormant owning read API; native company-auth composition; isolated native
  backend/browser tests and guarded assets; ADR 0070/current checklist.
- OPEN_QUESTIONS: privacy/named readers, real delivery/support, shared cache/
  workers, PostgreSQL, production origin/static/CSP and human/device acceptance.
- KNOWN_RISKS: free-text personal information, history materialization/group
  discovery cost, stale client data and premature operational admission.
- GLOSSARY_DELTA: React browser client includes the closed Complaints read
  integration; identity and owning workflow authority remain independent.
- NEXT_READ_QUEUE: review the closed Complaints candidate and finish M1 before
  real read admission; P3 and the TAT/Origination/Portal sequence remain gated.
- VERIFICATION: final executed results/limits are in the current release
  checklist and browser decision section 13; earlier counts are historical.

## 13. Primary-source references

Official sources support the trust-boundary recommendations, not the estimates or any claim about JBL's deployment. They were consulted during this research/planning work; recheck supported versions before implementation.

| ID | Primary source | Use |
|---|---|---|
| R1 | [Django 5.2 CSRF](https://docs.djangoproject.com/en/5.2/ref/csrf/) and [sessions](https://docs.djangoproject.com/en/5.2/topics/http/sessions/) | Cookie-write/session protections; not a reason to relax Telegram endpoints |
| R2 | [RFC 9700](https://www.rfc-editor.org/rfc/rfc9700.html) | Reviewed OAuth callback/code/PKCE protections |
| R3 | [OIDC claim stability](https://openid.net/specs/openid-connect-core-1_0.html#ClaimStability) | Verified issuer plus subject binding |
| R4 | [OWASP authorization](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html) | Current request authorization and default deny |
| R5 | [Render deployments](https://render.com/docs/deploys#zero-downtime-deploys) | Deployment behavior has configuration/application limits |
| R6 | [Render custom domains](https://render.com/docs/custom-domains) | Optional hostname feasibility, not deployed evidence |
| R7 | [ODPC assessments](https://www.odpc.go.ke/assessments/) and [official guidance](https://www.odpc.go.ke/guidelines-2/) | Early actual-flow/privacy review, including transfer/DPIA assessment as determined by qualified reviewers |

Repository controls: AGENTS.md, PRODUCTION_RUNBOOK.md, docs/production-release-record.md, .github/workflows/ci.yml, docs/ui-standard/README.md and docs/ui-standard/component-index.md.

**Findings:** source/standards guidance and runtime validation are distinct. **Open questions:** actual deployment and legal/support context. **Next steps:** review with the named business, IT and privacy owners before implementation.
