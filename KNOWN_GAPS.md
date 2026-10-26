# Known Gaps and Verified Workarounds

## Portal varied-data acceptance and remaining limits - 26 October 2026

The expanded local run passes 995 backend checks (six PostgreSQL-only skips),
271 Chromium checks and 858 requests across all 211 Portal route patterns.
Volume evidence covers 5,000 imported cases/Sheet rows, 1,000 BRO-created cases,
100 complete varied journeys and recovery of one whole 1,000-row SysUp source
after interruption at 360 committed rows. Original driver failures and their
independent postcondition checks are disclosed in the existing Portal audit.

Fixed: HB Actions drawer group mismatch for HB Staff/IT, expected Portal
exceptions becoming 500s, overlong BRO names and the SysUp upload-row ceiling.
Files are retained whole; internal matching defaults to 400-row chunks, while
approved writes keep the 20-row request budget. The existing upload-size guard
still applies. The old `SYSUP_MAX_ROWS_PER_UPLOAD` setting is obsolete.

Portal continuation runs while Imports is open; it is not a background approval
worker. Committed progress survives interruption; remaining rows can be reviewed
and resumed. Separate legacy token-review screens were not migrated to this
Portal continuation loop. Sheet money remains whole-KES presentation: 4,999.99
can display as 5,000, while canonical Portal eligibility correctly remains held.

Large FarmUp commits still need bounded processing: the 5,000-row local run
spent 307.0 seconds in one commit request. The in-process test client has no
reverse-proxy/worker timeout, so successful reconciliation does not establish
production readiness for that size. SysUp continuation does not change FarmUp.

No deployment, migration or real provider write occurred. PostgreSQL races,
production throughput/scheduling, real sharing/quotas and physical devices
remain unverified. See `docs/portal-miniapp-audit-2026-10-26.md` for source-bound
UI exceptions, exact datasets, artifacts and reproduction commands.

## Portal audit remediation - 26 October 2026

The reported Sheet alias, invoice-phone and Nairobi timestamp defects are fixed.
The existing Case History route is restored; TAT creation field errors no longer
echo submitted customer values. Current authorization and financial-finality
rules are unchanged. Retired order tests now require 426/no-write behavior;
current finalize tests retain local bytes, exact membership and version history.

The isolated run executes 990 backend checks: 984 pass, six PostgreSQL-only
checks skip, and none fail or error. All 269 Portal/FarmUp Chromium checks pass.
The real-backend synthetic journey completes SysUp/FarmUp, visits, approvals,
signed orders, PDF invoices, a mixed-mode signed payment and commissioning for
HB and Eco-conserve. All 32 integration operations succeed against local
Sheets/Drive substitutes, with no header repair or business-rule bypass.

PostgreSQL row-lock races/schema upgrade, real Google/Telegram/email delivery,
physical devices and production scheduling remain unverified. No production
data, deployment, dependency or setting was changed, and no migration is needed.
Before operational acceptance, run the six skipped checks under PostgreSQL and
the provider/device checks listed in
`docs/portal-miniapp-audit-2026-10-26.md`. Local logs, DBs, CSV projections and
retained workbook/blob evidence are under ignored
`test-results/portal-local-audit-2026-10-26/` and `test-results/portal-fixes-*`.

## Origination alignment and model cleanup - 23 October 2026

Implemented: strict placed-only filling (including no-layout drafts), signature
Edit/identity links, repeated slots with one capture, published-warning attachment
for Main/supporting PDFs, refreshed testing-deletion confirmation, and retirement
of two legacy authoring models. Full inventory and operator actions:
`docs/origination-model-audit.md`; UI evidence:
`docs/ui-standard/reviews/2026-10-23-origination-placement.md`.

Executed with synthetic data, isolated loopback PostgreSQL and mocked providers:

- Focused projection/editor/deletion/product-deletion suites: 160 passed.
- Final catalogue/setup/value-contract/advisory-publication suite, including
  unfinished Main OTP mappings and supporting meanings: 176 passed.
- Existing-client wire compatibility and strict field projection: 30 passed.
- Final signer-editor suite: 22 passed, including explicit omission of an ID
  link and continued editing of existing text-based phone links.
- Migration guard/upgrade/rollback: 2 passed; both nonempty legacy tables refuse
  removal, and application payload/frozen bytes survive the empty upgrade.
- Mini App placement browsers: 6 passed at 320/430/1280px in light/dark.
  Native authenticated Admin separately verifies Edit, save/reload (including
  quoted labels), duplicate signature/date slots, one participant and immutable publication, with
  390/1366px light/dark evidence. These are overlapping suites, not unique totals.
- The broader run executed 657 tests: 655 passed, 2 failed on existing validation
  wording assertions. Both reproduce on unchanged commit `0e9e6bd6`:
  `LoanOriginationServiceTests.test_saved_repeatable_security_repairs_blank_containers_and_grouped_amounts`
  expects “Year of purchase” but receives “number”; and
  `OriginationSafeWorkflowTests.test_invalid_draft_patch_identifies_field_without_logging_submitted_value`
  expects “amount” but receives “number”. Historical ownership/signing migrations
  were also exercised in the earlier 682-test run; that run was not fully green.

Legacy UI/assignment assertions were retired with their interfaces. Remaining
workflow fixtures now declare the PDF placements they intend to fill. Reused
test databases can lose migration-seeded policy/audit rows after transactional
flushes; validation restored only isolated test fixtures, never production grants.
Evidence logs are under ignored `test-results/origination-*` paths.
The API keeps its existing projection wire format, so already-open Mini App
clients receive the strict field list without a client protocol upgrade.

No deployment, production row-count audit, live OTP/SMS/Drive check or physical
Telegram-device check was performed. No new setting/dependency is required.
Standard release migration/static collection is still required. Migration 0012
locks and checks both legacy tables before removing anything and stops if they
contain records; reconcile/retain those records under the old release first.
Rollback recreates empty legacy tables/FK at Origination 0011 and requires the
corresponding code release. Signed bytes and external files are not rewritten.

## Specification 18 candidate - 23 October 2026

The native browser Complaints UI, evidence gallery and reporting corrections
are implemented with the existing recovery and PostgreSQL security boundary.
Current native test results, source-bound visual comparisons, review and
rollback are in `docs/runbooks/browser-channel-parity.md` and
`docs/ui-standard/reviews/2026-10-23-complaints-spec18.md`.
Production browser routes remain off/unmounted; physical devices, assistive
technology and named operational/privacy acceptance remain outstanding.
The runbook separately records existing environment-template, dependency
namespace and strict Sheet-header test failures; whole-repository CI is not
claimed green by this bounded change.

## Browser operational acceptance - 23 October 2026

The current extension covers settings, schedule and report-email recovery in
one tab, superseding the exclusion in the historical 22 October entry below.
Reload/tab closure still loses unsaved memory; never assume offline server save
or automatic replay. PostgreSQL-only native security state is governed by ADR
0074 and staff_auth migration 0004; production browser access stays gated.

One authorized synthetic email was accepted by the configured provider; the
mailbox owner confirmed Gmail receipt and successful Excel attachment opening.
The complete live browser/delivery/support drill is not yet accepted. No real
recipient address belongs in Git. Physical-device, assistive-technology and
named privacy/support approval cannot be inferred from Playwright or code review.
Current executed results and exact remaining acceptance are recorded in
`docs/runbooks/browser-channel-parity.md`.

## Closed Complaints recovery scope - 22 October 2026

The recovery slice resumes the work paused for `ui.txt`. Complaint creation
and case updates retain one tab-local unfinished task across same-account
native reauthentication, with explicit same-request confirmation after a lost
response. They do not promise an offline server save. Reload/closing the tab
loses unsaved text/files; use Save draft for server-retained text and select
attachments again after a reload. Explicit logout/discard and account/security
changes clear tab memory. See docs/runbooks/browser-channel-parity.md.

Unsaved preferences, scheduled-email editors and report-email tasks are outside
this slice's recovery contract. They must not be described as offline/session
safe. Real devices, retention/privacy acceptance, PostgreSQL/multiworker and
M1/production integration remain unverified; production stays off/unmounted.

The existing loopback review credentials were checked through actual native
password plus recovery-code MFA. Failed attempts can trigger normal rate limits;
refresh http://127.0.0.1:8769/_review/ for the running fixture's credentials and
an unused recovery code. Do not disable authentication checks. Restart the
foreground review helper to load new assets or reset its synthetic fixture.

## Closed native operations candidate - 22 October 2026

ADR 0073 adds a separate native browser candidate without expanding restricted
v1 or connecting the simulator to real services. Current scope/commands/evidence
and remaining acceptance are in docs/runbooks/browser-channel-parity.md.
The report slice adds canonical outcome/timing views and exact chart-to-table/
Excel selections. The continuity slice adds saved queue defaults, safe report
URL restoration and bounded activity pagination. It is not full production
parity: exhaustive offline/history/session-expiry draft paths, real providers,
PostgreSQL/multiworker operation, actual devices/privacy/design review and M1
remain open. Production routes stay unmounted and all browser flags default off.
The latest native synthetic review is started with
`scripts/start_complaints_local_review.ps1` at loopback 8769; the older simulator
on 8767 is separate. Keep its foreground terminal open and wait for readiness.

The `ui.txt` correction is applied only to the native operations entry. Restart
the 8769 review host to see it; startup-pinned assets intentionally do not change
mid-review. The UI correction alone did not complete offline/session-expiry/
ambiguous-write recovery; the bounded recovery slice is recorded above.
Native modal dialog and AG Grid composition
exceptions, dependency review and screenshot evidence are documented in
browser/DESIGN.md and docs/runbooks/browser-channel-parity.md. User approval,
real devices/assistive technology and production acceptance remain unverified.

## Local Complaints demo now accessible - 20 October 2026

P2a.2 / ADR 0072 extends P2a.1's synthetic review workspace at
http://127.0.0.1:8767/. It opens directly into demo cases without account setup.
The standalone server and verified fixture SQLite store do not initialize Django,
read deployment settings or touch operational/test databases. It remains available
until its process stops; browser/README.md documents restart. It is no installed
startup service, live staff admission or proof of company authentication.
Officer creation/uploads, HB feedback/resolution, Manager reopen/completion,
IT override and Portal-only denial now operate in a shared in-memory sandbox.
Refresh retains demo changes; Reset demo or server restart clears entered values
and uploads. These simulate built-in permissions, not deployment policy overrides.
Reports/export, voice/maps, real Drive/Sheet/Telegram publication and production
browser writes are not implemented by this demo. Native P2a remains read-only.
Native P2a authorization remains separately exercised. M1/privacy/named readers,
production topology, PostgreSQL and real devices remain open. Current evidence/
rollback are in decision section 15 and the release checklist.

## Closed Complaints browser connected; operational read pilot pending - 20 October 2026

P2a / ADR 0070 now connects native company password/MFA to existing Complaint
permissions and list/search/paging/detail/history in isolated synthetic tests.
The user approved starting this development alongside M1 readiness. A separate
React/ADS entry uses the existing dependency graph and current official design
references; the fixed preview and Telegram UI remain independent.

The candidate projection still includes personal free-text names/descriptions.
It is not an approved live privacy projection. Notes/diffs, raw messages,
phone/National ID, source identifiers, media/location and sync diagnostics are
excluded. History response is capped at 100 entries; the existing owning detail
service still materializes history before projection. Workspace discovery checks
current authority per enabled database group; production scale needs review.
No writes UI is supplied. Missing controls/references may be initialized by
existing read services and daily capability usage records count requests.

Production remains off/unmounted and E006 remains. Real delivery/support,
reviewed shared cache/worker operation, PostgreSQL, production origin/static/CSP,
devices/assistive review, named readers, privacy and M0/M1/M2 are still open.
Current verification and rollback are in the release checklist. P3 writes and
later workflows have not begun. Existing baseline audit findings below remain.

## Browser abuse boundary hardened; shared cache still required - 20 October 2026

P1b.2b.4 / ADR 0069 resolves spoofable forwarded-IP browser limits, native
throttle misdiagnosis and native cache-key privacy in the configured application
cache. Browser/setup network limits now follow native proxy/IP/IPv6 policy;
native form/view limits return JSON 429 and failures return safe unavailable
feedback without new assurance. Ordinary workflow keys and Telegram limits
retain their existing behavior. No new frontend step or dependency/schema.

The default cache is still process-local. E007/E008 now block attempted browser
activation without a reviewed shared backend/privacy hook, while E006 remains.
These checks are offline and do not certify service/client availability, shared
worker state, atomic add, consistency, capacity/non-eviction or deployed proxy
trust. Do not mount production routes or rotate/clear live security state to
make a check pass. Shared-cache approval/operation, real delivery/support,
PostgreSQL, production origin/static/CSP, devices and M0/M1 remain open before
Complaints admission. See the current plan/release checklist for evidence.
The existing environment-template checker still reports 119 omissions; the
artifact audit reports 17 allowlist hash mismatches, all byte-identical to HEAD.
Neither baseline is changed to make a check pass. Full CI is not claimed.

## Guided browser onboarding is connected; readiness remains open - 20 October 2026

P1c.6 / ADR 0068 connects native first-password and enrollment to short ADS
screens. Invitation proof is erased from the fragment before authentication requests/render;
verified setup and fresh QR drafts resume from their bound session. Recovery
codes are shown once with explicit copy/save. Password creation continues to
enrollment without another password prompt; fresh sign-in after saving codes
remains native policy. Lost one-time disclosure is never replayed.

This closes the local onboarding UI gap. Actual canonical-address invitation
delivery/verified support, PostgreSQL/shared-cache, production origin/static/CSP,
device/assistive and M0/M1 acceptance remain open before Complaints. The fixed
preview stays separate and production auth disabled/unmounted. No real account,
mail, grant, migration or deployment change. Current record: decision section 12.
The 119 pre-existing environment-example parity omissions below remain.


## Historical P1c.5 native sign-in handoff - 20 October 2026

P1c.5 connects a separate React build to the existing native password/MFA/session
boundary in isolated tests. It preserves usernames after errors, uses autofill
and resumes interrupted MFA without repeating password entry. An expired owned
cookie now permits a fresh sign-in without asking users to log out separately.
The fixed-value preview at 8766 remains unchanged. There is no operational auth
URL or newly admitted real staff; browser off/E006/routes remain closed.

Initial-password/enrollment/recovery-code handoff UI and actual delivery/support
are not completed onboarding. Keep those flows short and guided in the next
bounded increment; never substitute simulated success or silently issue MFA
assurance from setup. Production static/CSP/origin/shared-cache/PostgreSQL,
device/assistive and M0/M1 acceptance remain open. See ADR 0067 and decision
section 11 for current evidence and rollback.

The repository's existing environment-example parity check also fails with
119 missing declarations. Its checker, config/settings.py and .env.example
match HEAD; P1c.5 introduces no deployment setting. This baseline documentation
gap prevents claiming a clean full CI run and is outside this authentication slice.

## Browser composition corrected; design acceptance remains explicit - 20 October 2026

P1c.4 addresses the documentation-backed critique of earlier layouts. Use /
for the staff presentation and /review.html for synthetic Page/Theme/Response
selection on the loopback preview. Access forms retain one reading sequence;
the workspace uses actual ADS navigation; persistent section feedback and flat
surfaces replace popup/duplicated errors and nested sunken-on-raised groups.
Theme startup now precedes controls, avoiding briefly light fields with dark text.

Technical tests establish behavior/source binding and viewport fit. They do not
prove design quality, human/device/assistive acceptance or full ADS conformance.
Follow browser/AGENTS.md and DESIGN.md for current official references. Exact
graph/notice/asset and verification evidence: decision section 10. Browser auth
remains disconnected/off/E006/routes unmounted; operational M0/M1 remain open.

## Historical browser laptop viewport overflow correction - 20 October 2026

P1c.3 replaces P1c.2's narrow cards and stacked controls. At 1366x768 the previous
sign-in page scrolled 26px; expanded controls caused 480px overflow despite spare
horizontal space. Wide ADS grids, an adjacent control panel and compact token
spacing now address the layout cause. Checks explicitly cover short desktop
heights, all pages/form errors and expanded controls in both themes. See decision
section 9 for final results and limits. Mobile/large text may scroll to preserve
readability; no fixed-height/clipping workaround is used. The auth/operational
limitations below remain unchanged.

## Browser ADS adoption is implemented; operational access remains open - 20 October 2026

P1c.2 supersedes the earlier custom browser-layout exceptions. All existing
browser pages now use ADS layout/control/typography/navigation components and
typed semantic tokens; the complete recommended lint sets block style drift.
Use **Preview controls** at http://127.0.0.1:8766/ to inspect pages, themes and
simulated responses. ADS typography uses its supplied system-font fallbacks;
proprietary font files and Atlassian branding remain excluded.

The pages still use fixed read-only demo values and simulated responses. This
UI change supplies no real authentication or workflow access. Browser off/E006,
unmounted production routes, native transport/CSRF/mail/recovery/cache/privacy,
PostgreSQL, support and M0/M1 gates remain. Human/device/assistive review is not
inferred from headless captures. Full evidence and rollback: decision section 8.
Earlier sections retain their historical measurements and dependency limits.

## Actual ADS local client still needs native transport and M1 - 20 October 2026

The user's “resolve it and proceed” instruction now supports the bounded local
`browser/` React/ADS installation and build (ADR 0066). Use its README and
http://127.0.0.1:8766/ for actual ADS components. Earlier no-install/custom-only
statements below are historical. The old forensic manifest remains unsuitable
as an application manifest; only the separate exact workspace is accepted.

One original legacy context React-peer mismatch remains an explicit tested local
exception, never upstream support. The fixed development selector-parser override
and supported linter give a zero-finding point-in-time audit; deprecated vendor
stable/theme transitives remain maintenance concerns. Full notices accompany the
52 bundled packages; no brand/font/image asset is imported. Toolchain/native/MPL
redistribution requires its own distribution-specific notice/source package.

The actual ADS demo uses fixed read-only values and memory only. It supplies no
real session, proof delivery, password/MFA mutation, customer record or workflow
grant. Browser authentication remains off/E006 blocking/routes unmounted.
Production static/CSP/cookie/CSRF integration, interrupted setup/recovery,
shared native cache/log privacy, PostgreSQL, human/device/assistive review,
primary/backup ownership and M0/M1 remain open. Local inline theme styles and
hashed import maps are not a production CSP decision. An uninitialized native
feature-gate warning is observed without configuring a provider or sending data.

79 production-browser checks/71 synthetic captures and exact peer/context/parser/
type/lint/build checks pass. These do not certify full CI or real authentication.
Commands, diagnostics, checklist and rollback: BROWSER_REACT_ADS_DECISION.md
section 7. Previous environment-template/artifact/Python-audit gaps are unchanged.

## Accessible local wireframe is not working browser authentication - 20 October 2026

Run `python scripts/serve_browser_access_preview.py` and open
http://127.0.0.1:8765/ on the same computer to review the proposed access pages.
It is a first-party synthetic analysis artifact with read-only demo fields,
simulated responses and no API, credentials, storage, customer records or grants.
Refresh/Reset demo resets its memory; its one-time-view simulation is not a
durable security control. Do not enter real credentials or publish this tool.

The selected React/ADS client is still uninstalled. The declared React-16 peer
conflict was reconfirmed; no compatibility exception, licence/asset/notice/build
acceptance or M1 gate is waived. Local Node 26.7.0 is outside the review
candidate's >=22 <25 range; the later frontend needs a reviewed runtime.
Browser auth remains disabled and production URLs unmounted. Real proof delivery,
interrupted setup/recovery, shared native cache/log privacy, PostgreSQL and
support/staging acceptance remain separate. Section 6 of
`codebase-analysis-docs/assets/BROWSER_REACT_ADS_DECISION.md` records the candidate,
source-bound synthetic evidence, diagnosed preview fixes and rollback.

## Closed initial setup still needs delivery and operational acceptance - 20 October 2026

P1b.2b.3 adds an audited existing-account preparation service and unmounted
native mailbox/first-password handlers. Only exact active admitted non-Admin
accounts with unusable passwords and unambiguous canonical addresses qualify.
No usable password reset, new account, email-based identity merge, privilege or
workflow grant is supported. Same-session/request proofs and audit receipts
govern every credential write; no login or MFA assurance is issued by setup.

No proof dispatch/export exists: synthetic tests decrypt their own proof to
exercise the native backend. Actual mail delivery, safe link/log handling,
uncertain dispatch/retry and support acceptance remain unimplemented. Never mark
the address verified or print/send a capability through operator logs as a
workaround. Existing usable-password address verification/recovery remains a
separate verified-support boundary. Native callback/notification changes hold
setup until reviewed.

If setup expires or loses its anonymous session after mailbox verification but
before the first password, normal preparation deliberately refuses to downgrade
the now-verified native address. A separately reviewed resume/support procedure
is required before operational admission; deleting or un-verifying that address
is not a workaround.

First-password setting changes the exact account's Django session-auth hash and
can expire its existing Django cookies, including the Telegram session bridge.
Signed Telegram identity and grants survive; a fresh valid signed launch can
re-establish its session. Do not promise browser-only session revocation for a
password mutation or force browser password/MFA into Telegram.

Browser remains false, E006 blocking and routes unmounted. Migration
`staff_auth.0003_staffbrowsersetupgrant` is additive with no backfill; no real
preparation, password, provider, grant, merge or deployment action occurs.
Evidence, schema reversal and merge/deploy/monitoring checklist:
`codebase-analysis-docs/assets/STAFF_BROWSER_INITIAL_SETUP.md`. Remaining shared
native cache/log privacy, PostgreSQL, frontend/D13, owners and M0/M1 gates are not
waived; previous environment/artifact/dependency-audit findings remain separate.

Final combined isolated verification: **187 tests, 178 passed and nine
PostgreSQL-only skips**, including all 28 new SQLite cases. Two overlapping native
configured-hasher journeys, all 44 governance/tool tests, narrow Ruff, relevant
catalogue/static checks and isolated migration forward/reversal passed. The
expanded run uses a process-only fast synthetic password hasher and a dedicated
ignored local SQLite test database. Initial failed fixture assumptions and
current commands/limits are disclosed in the phase document. These results do
not certify full CI, PostgreSQL, live delivery, staging or M1.

## Shared TOTP guard is a bounded browser prerequisite - 20 October 2026

P1b.2b.2 adds shared one-use TOTP claims after native validation in the dormant
browser adapter. It addresses code reuse across independent native caches on
that adapter, not general allauth cache sharing or operational readiness. Generic
and headed allauth routes remain unmounted. Never expose them as an alternative
MFA entry point or clear unexpired replay claims to repair a failed login.

The local missing `django-allauth[mfa]==65.20.0` dependency was restored using
the existing pin. Native verification is retained; no dependency manifest,
frontend, global cache, Telegram credential policy or business role changed.
Migration `staff_auth.0002_stafftotpreplaystate` is additive, with no backfill.
Production deployment/migrations remain unknown; no real claims were provisioned
or cleared. Evidence, explicit reversal and the merge/deploy/monitoring checklist
are in `codebase-analysis-docs/assets/STAFF_BROWSER_REPLAY_GUARD.md`.

Controlled existing-staff provisioning, verified address/password setup,
operational recovery/helpdesk, shared native rate-limit/cache topology,
notifications, PostgreSQL races, staging/both-channel/support acceptance and M1
remain open. Browser stays false and E006 blocking; React/ADS acceptance is still
held. Existing environment-template, artifact and dependency-audit findings are
not waived by this increment.

Final combined isolated auth/Telegram/user-lifecycle run: **156 tests, 150 passed
and six PostgreSQL-only skips**, including all 14 new SQLite cases. All **44
governance/tool tests**, relevant static/catalogue checks and isolated SQLite
migration forward/reversal passed. A separate restored-dependency baseline used
the configured native password hasher (136 passed, four skipped); the final
expanded rerun used a process-only fast synthetic hasher. These are scoped local
results, not full CI or operational acceptance. Actual commands/limits are in
the phase document.

The pinned native TOTP cache key contains the submitted code. The synthetic
formatted-code test observed `CacheKeyWarning` including that key when whitespace
is submitted. The test captures this expected warning without printing even
synthetic codes; runtime warning suppression is not added. Native cache key/log
privacy must be reviewed and resolved with the remaining shared-cache design
before any operational browser mount. The new shared table stores HMAC only.

## Closed enrollment is not operational browser access - 19 October 2026

P1b.2b.1 adds native TOTP setup/one-time recovery handoff behind current admission,
fresh password recheck, encrypted storage and atomic audit. These are unmounted
backend handlers, not provisioning, a finished client or staff onboarding. Setup
does not grant MFA assurance; explicit logout and native password/MFA login follow.
Recovery-code response loss cannot authorize redisclosure/regeneration. Expired/
interrupted post-activation setup needs ordinary MFA login or separately verified
support; no authenticated factor-management UI is introduced here.

Browser stays off and E006 blocking. Controlled provisioning/address/password
setup, operational recovery/helpdesk, shared native replay/abuse cache, accepted
mail, PostgreSQL/staging/both-channel acceptance, support ownership and M1 remain
open. The HTTP DB throttles do not solve cross-worker TOTP replay. React/ADS
peer/licence/asset/build acceptance remains held; no frontend package installed.
Production release/migrations are still unknown. No schema/dependency/env name,
production route, real opt-in/reset, customer/provider write, merge or deployment.
Actual tests, remaining limits and change-specific monitoring/rollback checklist:
`codebase-analysis-docs/assets/STAFF_BROWSER_ENROLLMENT.md` sections 5–6. Historical
phase counts below are not current-phase certification or production evidence.

Final focused run: 140 tests, 136 passed, four PostgreSQL-only skips, including
two new enrollment/handoff races not executed locally. All 23 new SQLite setup
tests and 44 governance/tool tests pass, as do Node and relevant fast checks.
The 119 environment-template omissions and 17 tracked-artifact hash mismatches
remain. No full CI, shared-cache, real device, staging or production certification.

## Browser dependency graph is review-only, not installable - 19 October 2026

D13a collects exact frontend dependency/archive/licence evidence; it does not
clear ADS standalone use or approve a frontend build. No packages, fonts or icons
were installed and no browser route/flag was opened. Root manifests and existing
Telegram/Django runtime are unchanged.

Strict resolution without the forensic overrides fails because
`@atlaskit/analytics-next@12.6.0` requires
`@atlaskit/analytics-next-stable-react-context@1.0.1`, which declares React
`^16.8.0`; proposed staff UI dependencies include React-18-only peers.
`@atlaskit/browser-apis@1.2.0` also rejects React 19. Literal React 18 overrides
permit a graph for archive inspection, **not a compatibility-approved install**.
Do not use force/legacy-peer flags or relabel that graph as supported. Choose a
maintained compatible set, or obtain an explicitly reviewed compatibility
exception backed by actual source/runtime tests, before frontend installation.

Pending licence/asset/notice acceptance, actual build/lint/browser behavior and
operational MFA acceptance remain separate gates. Offline report consistency
does not prove legal clearance, runtime privacy, security or compatibility.
Evidence, executed checks and phase-specific merge/deploy checklist:
`codebase-analysis-docs/assets/BROWSER_REACT_ADS_DECISION.md`, section 5.

Final D13a inventory: 529 unique artifacts / 546 locked entries, all inspected
without remaining errors; 44 governance/tool tests and offline snapshot binding
passed. There are 63 missing matched shipped licence/NOTICE-file indicators
(four runtime), 53 nested-metadata indicators, six asset-bearing packages and
13 development-only MPL-2.0 artifacts. Indicators overlap and are not proven
licence violations. Preserve focused review of exact terms/notices, assets and
distribution model; none is cleared by the tooling pass.

## Browser JSON contract and React licence gate - 19 October 2026

P1b.2a adds a dormant JSON password/MFA/session/logout adapter and protected
pending-enrollment storage, not a usable standalone frontend or finished
enrollment/recovery. `STAFF_BROWSER_AUTH_ENABLED` remains false, readiness
remains blocking, and production auth/business routes are unmounted. Future
business endpoints require the company-browser guard **and** owning-workflow
authorization; a password-only or ordinary Django session is insufficient.

The user selected React/ADS for new browser pages and exact licence review first.
Five direct Atlaskit package declarations and tarball licences/integrities were
inspected; no complete transitive/asset clearance exists. No frontend packages,
assets or build are installed. Do not infer standalone permission for every ADS
material, replace Telegram UI or bypass the Design Lab migration hold.

Shared allauth replay cache, provisioning/email/password setup, operational
enrollment/recovery, support/offboarding acceptance, reviewed React UI/build and
real staging/both-channel acceptance still block activation. Initial DB-backed
request throttling does not solve cross-worker TOTP replay protection. No new
migration/env variable/dependency is added in this slice. Current verification
and per-release checklist: `codebase-analysis-docs/assets/STAFF_BROWSER_JSON_AUTH.md`;
licence/build gate: `codebase-analysis-docs/assets/BROWSER_REACT_ADS_DECISION.md`.
No production release/inspection, merge, real opt-in/reset or provider write.

Final focused run: **115 tests, 113 passed and two PostgreSQL-only concurrency
skips**. All 17 new JSON/storage tests, existing native headed-login fixtures and
Telegram/user lifecycle regressions pass. Also passed: 28 governance-script tests,
Node tests, syntax, architecture, route inventory, migration graph, model/dependency
checks and regenerated catalogue. Wider environment-template parity still has
119 missing names; the artifact audit still reports 17 prior allowlist hash
mismatches. No baselines were relaxed. These results do not establish full CI,
PostgreSQL, React, staging, live-device or production readiness.

## Browser lifecycle backend controls - 19 October 2026

P1b.1 provides deliberate browser opt-in, suspension, browser-only revocation
and audited factor reset, **not usable browser login/enrollment/recovery**.
Keep `STAFF_BROWSER_AUTH_ENABLED=False`; activation checks remain blocking.
Do not use `manage_staff_browser --apply` against real staff without the actual
environment-specific authority and accepted support procedure. It defaults to
read-only preview. No workflow grants, credentials or emails are provisioned.

`staff_auth.0001_initial` adds one admission table without backfill; normal
rollback retains it and its revocation state. The generated catalogue is now
refreshed and verified (213 entries), resolving P1a's stale usage-map finding.
Other previously diagnosed audit/environment/Ruff limitations remain separate.
The wider catalogue test suite also reports an existing duplicate explicit
`RequisitionBatch.order_number` index; its finance schema was not changed here.
Current verification, PostgreSQL-only race tests, remaining operational controls
and per-release checklist are in
`codebase-analysis-docs/assets/STAFF_BROWSER_LIFECYCLE.md`. No production release,
migration, opt-in, reset, external write or merge was performed for this phase.

Final focused normal-management-command result: **97 tests, 95 passed and two
PostgreSQL-only concurrency skips** across `staff_auth`,
`core.tests_telegram_authentication`, `core.tests_user_identity` and
`core.tests_user_hard_delete`. Ten final no-database crypto/configuration checks
also passed (nine overlap that run; one is the later generic-registration
contract), and 28 governance script tests passed. An earlier programmatic runner
missed the repository's test-mode argv marker and produced fixture-guard errors;
that diagnostic is superseded by the normal-run result, not a production finding.

## Dormant staff browser MFA verification - 19 October 2026

P1a `staff_auth` is an integration foundation, **not a usable browser login**.
Keep `STAFF_BROWSER_AUTH_ENABLED=False`. No production login/enrollment/recovery
or business URL is mounted; activation is deliberately rejected by system and
pre-migration production checks. Telegram signed-launch access remains unchanged.
Do not mount allauth's generic URLs or use vendor Admin JSON edits to bypass
unfinished account provisioning, MFA enrollment, audited recovery and revocation.

Current technical contract, verification and change-specific release checklist:
`codebase-analysis-docs/assets/STAFF_BROWSER_MFA_FOUNDATION.md`; decision: ADR
0060. Pending enrollment secrets need explicit protection beyond stored-factor
encryption; vendor replay/rate-limit cache must work across workers. Real
PostgreSQL, operational support, mail, privacy and live-device acceptance remain
required before browser admission.

Final focused run: **53 tests passed** across `staff_auth`,
`core.tests_telegram_authentication` and `core.tests_user_identity`; 28 governance
script tests also passed. Django checks, migration drift/graph, model governance,
architecture/write-route/UI checks and isolated vendor schema reversal passed.
These are synthetic SQLite results, not production or PostgreSQL evidence.

Broader checks are not fully green: environment parity reports 119 existing
missing variables (same at HEAD; all three new variables documented), the
dependency-audit exception expired on 2026-09-30, generated database catalogue
usage references from earlier HB Deposits/Portal work are stale, 17 existing
logo/screenshot artifact hashes disagree with their allowlist, and Ruff is
not installed locally. No exception extension, artifact baseline update, unrelated configuration rewrite
or catalogue regeneration was bundled into this phase. Full CI and production
readiness are not established by the focused tests. No commit/merge/deployment
or production migration was performed.

## HB Deposits implementation verification - 19 October 2026

The pre-visit HB Deposits workspace, cumulative-total audit, FarmUp ownership
protection, office intake-only outcome and KES 5,000 server-side JBL gate are
implemented locally. Operational guidance, API contracts, source-bound UI
candidate evidence and reversal procedures are in
`codebase-analysis-docs/assets/HB_DEPOSITS.md` and ADR 0059.

Final isolated verification:

- **235 focused backend tests: 233 passed, two skipped.** Suites:
  `hb_operations.tests_deposits`, `core.tests_portal_hardening`,
  `hb_operations.tests`, `core.tests_portal_imports`,
  `core.tests_workflow_capabilities.WorkflowCapabilityPolicyTests`,
  `core.tests_pipeline.JblPipelineServiceTestCase`, and
  `core.tests_portal_approval_controls`. The skips are specifically the new
  PostgreSQL edit/edit and edit/visit concurrency tests; SQLite is not locking
  evidence. The run used a fresh in-memory database and blocked socket connects.
  A follow-up three-test, no-database run also passed after the final ASCII-only
  amount/SQL-cast guard refinement. Its amount checks overlap the focused suite;
  the added cast-guard test explains the subsequent one-test increase on discovery.
- **268 Portal browser checks passed**, including source-faithful deposit
  light/dark mobile screenshots, audit/read-only access, stale/interrupted saves,
  queue filters/paging, held cards and office capture gating. Synthetic Chromium
  evidence is not human design approval, real Telegram acceptance or proof that
  production fonts loaded. No approved visual baseline was changed.
- Django system checks, migration drift/graph (275 migrations, 16 leaves),
  architecture boundaries, database governance, the 202-entry write-route
  inventory, UI source ratchet, 147 first-party JavaScript syntax checks and all
  Node/client checks passed. Ruff is not installed; no dependency was added to
  obtain it.

A wider 345-test diagnostic run was not green. In addition to subsequently
corrected funded-visit fixtures and exact retained-workbook hash fixtures, it
exercised older `JblPipelineApiTestCase` expectations for retired case-history
routes, 426-retired workbook endpoints, obsolete report/HTML/invoice contracts
and finance snapshots. A separate access-hardening assertion expects an exact
capability set without the existing mandatory Origination staff-signing grant.
Those unrelated contracts were not redesigned in this deposit change. The full
backend suite has not been certified; do not use the focused count as a claim
that every historical test or integration passes. Earlier diagnostic logs are
not the final result; `test-results/hb-deposit-final.txt` is the final backend
run. A discarded custom test-database reuse attempt produced missing-table
errors after settings overrides; the standard fresh in-memory rerun above
replaced it. Use the normal test database lifecycle on Windows.

No local PostgreSQL server/client was available, no operational database or
customer financial records were inspected/changed, and no real Sheets, Drive,
Telegram or paid API calls were made. Production deployment and migration
`0208_hb_deposit_capabilities` remain separately authorized release actions.
Preview legacy deposit-only review candidates for an explicitly selected group
with the documented reconciliation command; `--apply` additionally requires an
active Superuser actor and separate authorization for production data changes.
Do not auto-import staged/held rows or clear unrelated review blockers.

Before production acceptance, run the PostgreSQL race tests, review actual
scoped impact counts, verify existing access-policy refresh and test on real
Telegram devices. No new environment variables, persistent tables, external
dependencies, Sheet columns or runner schedules are required.

## Portal hardening verification - 19 October 2026

The JBL office-lead response defect and new order/payment document ordering
are corrected. New documents use original HBG visit/sign date (Nairobi
creation-date fallback); payments group Eco-conserve before HB. Retained
preview rows, signed files, numbering, financial values and access policy are
unchanged. See the Portal hardening section of
`codebase-analysis-docs/CODEBASE_KNOWLEDGE.md` and the current operational
contract in `docs/runbooks/portal-action-confirmations.md`.

Final isolated verification: 297 backend checks, 294 passed and three skipped;
all 261 Portal browser checks passed. The skips are two PostgreSQL-specific
claim/schema-upgrade checks and the optional local reconciled-workbook fixture
absent from this checkout. The earlier broad run's duplicate-retention assertion
was traced to equal-clock fixture timestamps; distinct explicit ages now make
both that test and payment pagination deterministic. Earlier payment-history
and product-label failures were corrected with genuinely scoped history
fixtures and the canonical saved label, without relaxing production guards.

Architecture boundaries, the complete 201-entry write-route inventory, Django
checks, JavaScript syntax/client tests, database governance, migration graph,
migration-drift and UI-source ratchet checks passed. Browser fixtures now load
the current shared confirmation/download contracts and assert the current
compact preparation/recovery interactions. No operational UI source, approved
baseline or design-lab migration flag was changed. Synthetic 320px light/dark
screenshots were inspected; they are not native-font or Telegram approval.

No production deployment/migration, real provider write or PostgreSQL run was
performed. There is no schema/environment/backfill requirement for this patch;
deploy the reviewed code normally and retain all historical documents. Real
Telegram devices, native downloads, live integration health and PostgreSQL
concurrency still require authorized release verification. The full repository
suite and correctness-only Ruff lint were not run (Ruff is unavailable locally).
Unrelated older parity/artifact/platform findings below are not resolved by
this bounded Portal patch. Older references below to the 34 inventory gaps and
direct requisition-event write are superseded by this verification.

## Origination phone registration pilot - 19 October 2026

The feature remains disabled by default. Synthetic HTTP/browser verification is
not evidence that the paid Safaricom subscription works. Before enabling it,
complete approved commercial/privacy onboarding, a separately authorized
synthetic sandbox check, PostgreSQL concurrency tests and real Telegram/native-
font UI review. No local PostgreSQL listener or guarded test URL was available;
the two row-lock tests explicitly skip on SQLite. Do not replace their assertions
with SQLite success or permit automatic provider retries as a workaround.

The first published tariff is interpreted as KES 4.50 per billable call, not a
flat price for the volume band. Confirm taxes, failed-call charges and volume
treatment in the signed agreement. The 50/day dispatch counter is a conservative
safety control, not a financial invoice. Reuse exact results for thirty days;
on uncertainty use only a new explicit confirmation after review.

Existing settings/environment parity (119 findings), unsafe-route inventory
(34 findings) and the direct requisition event write in
`core/api/portal_views.py::portal_requisition_finalize` remain outside this
change. The first two counts were reproduced against HEAD source in memory;
new feature settings/route are covered. Broader legacy policy/authentication
assertions and final evidence are documented in
`codebase-analysis-docs/assets/PHONE_ID_CHECK_VERIFICATION.md`.

## Origination document management verification - 16 October 2026

Manage documents and supporting-form changes pass 164 focused PostgreSQL checks
and 100 browser checks using synthetic data. Six failures in the broader legacy
Origination suites reproduced against HEAD service/source in memory: repeated
number validation wording, Published reusable document wording, remote-signing
copy, and three stale editor/stylesheet cache-version expectations. See
`test-results/document-management-baseline.log`; these checks were not weakened.

Real Telegram and deployed-font verification remain outstanding. No production
or external-service writes were made. See the document-management section of
`docs/runbooks/origination-ui-and-downloads.md` for the shipped behaviour and
source-bound screenshots. Repeated copies of one supporting template, such as
two independent guarantor documents, remain outside this change.

## Advanta SMS deployment verification - 16 October 2026

Advanta remains optional and no live SMS was sent during implementation. An
approved sender and enabled transactional route must be confirmed with Advanta.
No documented authenticated callback contract or provider idempotency token is
assumed; authenticated polling and single-attempt submissions are supported.

Provision `process_origination_deliveries --apply` once per minute and verify
its heartbeat before relying on delivery tracking. Hosting scheduler setup and
real handset delivery remain unverified until an authorized rollout. Existing
links retain their provider, so keep its credentials until expiry/replacement.
An uncertain invitation needs an explicitly replaced link, not replayed sending.
See `docs/origination-otp-integration-setup.md` for cutover and rollback.

## Existing regression gates checked during Advanta work - 16 October 2026

An untouched `34a13822` worktree on a fresh synthetic PostgreSQL database ran
390 tests with three failures, also observed in the broader SMS worktree run:

- `core.tests_reliability.MiniAppWritePolicyTests.test_tat_create_returns_categorized_validation_without_raw_input`:
  a synthetic phone value is echoed inside field-level validation details.
- `core.tests_reliability.MiniAppWritePolicyTests.test_tat_update_accepts_header_retry_key`:
  the existing mocked TAT update path returns 500 instead of the expected 200.
- `core.tests_production.ConditionalApprovalProductionReadinessTests.test_conditional_approval_requires_an_active_integrity_checked_policy`:
  the test still expects the historical consent-policy requirement for new
  applications; current short-acknowledgement readiness no longer emits it.

These are not fixed by changing SMS providers. The same untouched HEAD also
has 119 environment-example parity findings, 12 undefined names in the Portal
JBL visit path around lines 7980-7994, and existing PNG artifact-allowlist hash
mismatches. No operational UI baselines or artifact hashes were replaced to
hide these findings. Focused SMS checks and broad regression results must be
reported separately; none proves production readiness for the entire platform.

Reusing `--keepdb` after transaction/migration suites can leave migration-seeded
reference rows absent and produce additional access/notices/compliance fixture
failures. A fresh synthetic PostgreSQL selection of 72 tests covering those
paths plus Advanta passed. Recreate an isolated test database before interpreting
such failures; do not repair production grants to compensate for test fixtures.

## Portal finance browser wording assertion - 15 October 2026

`portal_nested_finance_layout.spec.js` expects "2 possible duplicate invoices"
in its invoice-review test; the current invoice card says "2 duplicate invoices".
The test and invoice implementation match HEAD and are unchanged by the payment
preview-reference fix. All eight new payment-preview identity checks pass. This
wording assertion remains unresolved; do not claim the entire finance suite passes.

## Origination application copies and unsigned completion - 15 October 2026

- Multiple different supporting documents are supported; repeated instances of
  one guarantor template are not. Two guarantors do not automatically produce
  two separately bound guarantor forms.
- Older approved applications without trustworthy page-boundary metadata retain
  combined downloads only. Individual signed copies are never reconstructed.
- Local synthetic browser checks cover the chooser and Telegram/browser handoff,
  not a real device's file-opening behaviour. Production deployment and
  PostgreSQL concurrency remain unverified locally.
- Signature-free completion applies to newly created catalogue applications;
  historical application and signing snapshots are deliberately not backfilled.

## Origination non-OTP readiness review - 15 October 2026

Origination is not given unconditional production sign-off. The detailed review,
reproductions, evidence and recommended order are in
`docs/audits/origination-readiness-2026-10-15.md`.

- Evidence HTTP 202/pending can incorrectly show "Evidence uploaded securely."
  Replaying an abandoned pending reservation does not resume storage. Verify
  the saved evidence list; neither the toast nor repeated same-key retries prove
  completion. Recovery needs a bounded lease/reconciliation fix, not blind retries.
- Withdraw for changes returns to Draft; it is not ordinary cancellation. There
  is no officer discard/cancel action. Testing deletion is not a business workaround.
- Ten-row paging still calculates actionability over the authorized workload.
  A synthetic Operations probe made 162 SQL queries for 10 authorized legacy
  applications and 267 for 100, returning ten rows in each. This is not a latency
  or deployed load test.
- Broad pre-change baseline: 545 checks, 525 passed, 12 failed, 3 errored and
  5 skipped. Many failures are outdated assertions/fixtures; the report records
  their categories. Concise queue status labels are now fixed and tested.
- Real Admin maintenance passed. The custom-PDF browser script stops at the
  intentionally removed lending-fields shortcut. The attachment fixture lacks
  its required applicant signer and correctly cannot publish the product. These
  two unsuccessful journeys are not current end-to-end production evidence.

The requested card/identity/publication changes separately passed 127 focused
checks on fresh SQLite/Python 3.14, with one PostgreSQL-only skip, and all 46
browser checks. An intermediate cached-database rerun lost migration-seeded
singletons after live-server test flushing; its resulting access/audit failures
did not reproduce on the fresh final database and are not application findings.

Only authorized full-access Origination views show unredacted identifiers.
Publishing with no signature requirements does not remove a product/application's
separate signing requirements or rewrite any existing signed document. Source
integrity, valid geometry, scope, revision and shared-change checks remain.

Production Python 3.12/PostgreSQL, native Telegram Android/iOS downloads/camera,
idle/restart runner recovery and actual OTP/carrier delivery remain unverified.
Normal code/static deployment is required; no schema or environment change, live
provider write, deployment or historical data conversion was performed here.

Repository-wide gates still report 34 existing write-route inventory omissions
and 17 artifact allowlist hash mismatches. None of those routes/artifacts or
their allowlist entries were changed here. The documented
`scripts/check_repository_artifacts.py` command is absent; the actual
`scripts/audit_tracked_artifacts.py` checker was run. These gates are not green.

## Portal confirmations and direct IT settings - 15 October 2026

Local SQLite/Python 3.14 checks cover routine confirmations, invoice holds,
payment eligibility with a SysUp product label, direct TAT IT saves and scoped
denials. Browser screenshots cover 320-1280px, keyboard operation and both themes.
Production Python 3.12/PostgreSQL locks and actual Telegram devices remain
unverified. Run the affected suites on staging before release; do not remove
identity, signed-document or financial approval guards to bypass a failure.
The two baseline payment-document failures below remain unchanged.

The product-mapping message was advisory in the inspected code, not the actual
selection blocker. It is removed from payment readiness. If an existing case
still cannot be added, use its stated readiness reason to correct the order,
invoice, identity or approval facts; arbitrary product text never grants access.

## Portal invoice corrections - 15 October 2026

Corrected-invoice, exact-duplicate, unmatch and letter-download regressions are
covered locally with synthetic data and actual Mini App renderers. The reported
uneditable confirmation note did not reproduce before changes in local Chromium;
foreground focus/input and preservation after server failure are now tested.
Android/iOS Telegram and a physical file saved on-device still require release
verification. A download request/acceptance is not proof the device saved a file.

No PostgreSQL test URL is configured locally; SQLite does not verify row locks.
Run the PostgreSQL-only correction concurrency tests before production release.
The broader payment-document suite has two baseline failures reproduced with the
unchanged Portal view code: `test_document_history_lists_and_opens_final_payment_snapshot`
(an empty historical document list) and
`test_payment_workbook_generation_uses_ready_farmer_and_preserves_signatures`
(`BIOGAS` versus expected `BIOGAS PREMIUM`). They remain outside this correction.

No data backfill or silent historical correction closure is performed. Existing
unfinished requests close when explicitly unmatched; retained letters/agreements
and previously signed payments remain history.

## Actionable Mini App recovery - 15 October 2026

Portal, TAT, Complaints and Origination now have owner-scoped App status lists
with ten entries per page, existing retry controls, explicit administrator
handoffs and support-reference copying. Portal bell actions no longer disappear.
Core migration 0205 adds only the approved TAT IT Sheet retry default and policy
version refresh; deploy it through the normal release process. See
`docs/runbooks/miniapp-recovery.md` and ADR 0052 for exact coverage/rollback.

Credentials, missing templates, unresolved case bindings and identity conflicts
still require the stated configuration/case repair; recovery does not bypass
those checks. Historical payment storage and exhausted/missing source uploads
use an explicit administrator handoff, not a new payment/import. Scheduled
email issues check an existing delivery, never issue another Send now; one-off
exports keep their existing owner/status dialog. Pending work still needs its
existing workflow runner. No scheduler or automatic bulk retry was introduced.

Verification includes 170 passing backend scenarios on a freshly migrated,
isolated SQLite database, plus the focused recovery rerun. Three concurrency
checks require PostgreSQL and were skipped, including the new simultaneous TAT
retry check. All 81 browser scenarios passed; light/dark mobile screenshots were
inspected and the status-header right alignment is asserted, with real-controller
checks for Origination and Complaints Settings. Actual Telegram devices, provider recovery and production deployment
remain unverified. No production provider writes or migrations were run.

Repository-wide checks still fail on the same 34 write-inventory omissions
confirmed against HEAD and 17 existing artifact allowlist hash mismatches. The
three new POST routes are inventoried; no allowlist hashes were changed.

## Portal isolation and Performance - 15 October 2026

Portal Home/bell background-failure projections are restricted to Portal-owned
operation types. The compact standings, milestone details and ten-case current
awaiting-visit list use existing Portal permissions; scoring, snapshots and
other Mini Apps' roles/data/processors are unchanged. Reopen the Mini App after
the normal deployment to load the versioned assets; no migration is required.

Local verification: 56 backend tests passed, one PostgreSQL-only concurrency
test skipped. The 93-test browser regression suite passed, with 13 final layout
checks and two navigation/dark-mode rechecks after visual refinements. Actual
production/Telegram-device behaviour and PostgreSQL concurrency remain
unverified; no production deployment or provider writes were performed.
See `docs/portal-qa-human-checks.md` for operational acceptance steps.

The tracked-artifact audit still reports 17 pre-existing hash mismatches
(logo and older Portal snapshots). HEAD already had 19; this change refreshed
only two inspected synthetic score-details heading snapshots and their exact
allowlist hashes. The unrelated mismatches were not silently approved.

## Origination usability and JBL Apps - 14 October 2026

Signature-font packaging, incomplete application copies, queue/filter layout,
signing actions, opposite-end preview navigation and Complaints table reveal
are implemented. The read-only `/apps/` chooser uses each Mini App's current
grants. No production deployment, role-policy change or Telegram configuration
was performed. See `docs/runbooks/origination-ui-and-downloads.md` for BotFather
cutover and real-device checks.

Focused isolated SQLite checks: 85 passed, one PostgreSQL-only concurrent signing
test skipped. Browser checks: 185 passed, plus four final dark-mode/toolbar
rechecks after visual refinement. Checks use synthetic/intercepted data and screenshots
were inspected in light/dark mobile layouts. Actual Telegram Android downloaded
file opening still requires verification after deployment; the app cannot
control Telegram's viewer or the device's file associations.

The tracked-artifact audit remains red on 19 pre-existing allowlist hash
mismatches: the logo and older Portal inbox/recognition screenshot baselines.
Comparing the committed HEAD bytes against the committed allowlist reproduces
all 19 mismatches. These files and their allowlist entries were not changed.
Ruff is unavailable in the local environment; Python/JavaScript syntax checks,
Django checks, migration drift and whitespace checks were run instead. The full
repository suite was not run.

## Complaints email layout and reconciled counts - 14 October 2026

Needs attention is now full-width, followed by two matched chart panels. New
captures separate same-period new-complaint resolutions, older resolutions and
current reopenings from the current open/overdue backlog. Shared email headers
place Data as of below the branding, keep comparison periods on one row and
omit unrestricted scope text from subjects. No permissions, workbook cohorts,
schedule settings or frozen delivery payloads are rewritten.

Full report_delivery regression suite on isolated SQLite: 140 passed, no skips.
Final focused presentation/data checks: 55 passed. Final Chromium email/dialog
suite: 88 passed, covering the three Complaints presets, shared Portal/TAT
headers, paired graph dimensions, 320-1280px layouts, cross-year single-row
stamps and light/dark states. Rendered screenshots were opened and inspected.
Ruff, JavaScript syntax, Django checks, migration drift and whitespace checks
pass. Offline PNGs use existing Pillow only; no new dependency or migration.

Actual Gmail/Outlook behaviour, automatic dark-mode image inversion and live
inbox delivery are not certified by browser previews. No real emails, provider
writes or production changes were made. PostgreSQL and the full repository
suite were not rerun for this presentation-only change. Details and logs:
docs/reports/complaints-email-layout-2026-10-14.txt.

## TAT BM action access and oldest-case names - 14 October 2026

Three focused tests reproduced the BM/IT denial before the fix. The built-in BM
capability no longer depends on available products or a cached product catalogue.
Migration 0204 provisions missing TAT defaults during normal release migrations,
preserving explicit BM denials, scoped grants and other Mini Apps' policies.
No special BM access command is required. Existing case snapshots are unchanged.

Final focused backend: 64 passed. Final real-template Chromium: 67 passed.
Customer-name screenshots at 390px and 1280px were opened and inspected; duplicate
names still open distinct cases. Django checks, migration drift, Ruff, JavaScript
syntax and diff whitespace checks pass. This is local verification, not a deployed
or authenticated Telegram smoke check; Render's actual pre-deploy configuration
was not inspected. The older baseline failures documented below remain open.
Handoff: docs/reports/tat-bm-access-2026-10-14.txt.

## TAT remarks and Telegram Web delivery - 14 October 2026

Implemented append-only remarks, scoped/current staff authorization, attributed
Sheet text, clear stage timing/activity, reviewed Mini App framing and named
native XLSX response headers. No workflow clock, completion state or score is
changed by a remark. Failed Sheet delivery is durable; an active Superuser can
requeue selected failed remark operations in Integration Operations Admin.

Verification: 75 focused local PostgreSQL tests passed, including real concurrent
same-key and different-comment saves. Final focused SQLite: 76 tests, 74 passed,
2 PostgreSQL-only skips; this includes the later Admin retry control. A subsequent
12-test activity pass verifies saved-name retention and unchanged grouping.
Chromium real-template interception: 65 passed, with light/dark screenshots at
320/360/390/430/768/1280px; the changed detail/activity layouts were visually
inspected at 320, 390, 768 and 1280px. Native SDK acceptance, cancellation, thrown
errors, unsupported clients and exact filename parameters are synthetic tests.

Broader SQLite: 272 tests, 258 passed, 7 failures, 5 errors, 2 skips. Unchanged
HEAD e8ea2c65, in its own worktree/cwd: 249 tests, 237 passed, the same 7 failures
and 5 errors. Exact failing test names match. These cover older creation,
correction/final-amount and signature fixtures and stale static UI assertions.
The route inventory has the same 33 pre-existing gaps on both revisions; the
new comments endpoint is inventoried. No access or workflow guard was weakened.
Ruff, all Node contract suites, 129 first-party JS syntax checks, Django checks,
migration drift, migration graph and diff whitespace checks pass.

Raw .txt outputs are in test-results/tat-remarks-*.txt; the handoff is
docs/reports/tat-remarks-telegram-web-2026-10-14.txt. An early reused test database
had been flushed of migration seeds; clean runs removed those harness failures.
The new --fresh-database runner flag recreates only its disposable local test DB.
The task-owned loopback PostgreSQL cluster was stopped after verification.

Deploy and apply core 0203_tat_event_role_attribution through the normal approved
release process. The existing process_tat_notifications runner now drains remarks;
no new schedule, setting or dependency is required. Rollback requires checking
that saved actor_role values fit 80 characters before migrating core back to
0202_jawabufarmermaster_requisition_batch_and_more. Existing notes/history survive.

No production migration, deployment, provider write or real staff session was
used. Actual Telegram Web authenticated launch and the physical native download
dialog still require a post-deployment smoke test. Correct headers address the
documented download contract, not proof that every Telegram-client bug is fixed.
Google cannot atomically compare and write a Sheet layout; pause row/column
sorting and structural edits during publication. Per-case publication locks
serialize concurrent note/stage writes, so saves on that same case may wait for
a publication transaction. Local Python is 3.14; deployment Python 3.12 is untested.

## Named Sheet columns and BM analysis approval - 14 October 2026

Focused, freshly migrated local PostgreSQL: 197 passed, including real concurrent
successor preparation and BM decisions, branch-scoped authorization, named-column
movement/ambiguity/freshness, durable publication, unknown/formula preservation,
cleanup guards, expired-version exclusion and lost audit-response recovery.
The task-owned loopback PostgreSQL cluster was stopped after verification.

Real-template intercepted Chromium: 59 passed at 320/360/390/430/768/1280px,
including the new BM stage, queue/search, forms, reports and native-button
contracts. BM screenshots were visually inspected at 390 and 1280px. A disabled
credit-assessment card was visibly present despite its hidden attribute; its CSS
now honors that state. Assets remain based on the existing TAT layout, not a new
design. Screenshots are under `test-results/named-columns-tat-browser-final`.

Broader SQLite: 562 tests, 527 passed, 28 failures, 6 errors, 1 PostgreSQL-only
skip. All 34 failing test names also fail on unchanged HEAD `d09f1e1d`, whose
comparable 532-test run had 29 failures, 9 errors and 1 skip. Outstanding failures
cover legacy TAT creation/correction/signature fixtures, static UI assertions,
SPIN submission, FarmUp identity/date expectations and order-review validation.
No workflow or access safeguard was weakened to make those tests pass. One
intermediate run overlapped SQLite test processes and hit a database lock; the
final non-overlapping rerun removed that harness failure.

Pinned Ruff 0.16.5 on changed Python files, Node contracts including all five
supported Apps Scripts, 129 first-party JavaScript syntax checks, Django checks,
migration drift and diff-whitespace checks pass. Raw `.txt` outputs are retained
in `test-results/named-columns-*.txt`; the handoff report is
`docs/reports/tat-bm-named-columns-2026-10-14.txt`.

No production schema, configuration, provider, deployment or existing case
snapshot was changed. Add the three unique BM headers and explicitly review and
publish selected product successors before new cases use the stage. A published
Origination definition sharing the source terms must be coordinated separately;
the rollout does not silently disable or rebind it. Current BM routing and an
explicitly agreed target also need operator review; no target means unrated.

The two obsolete TAT Apps Script source copies were removed by user approval,
recoverable from Git. Their live web apps/triggers must still be disabled by a
Google owner. Other scripts reject positional permission shortcuts; repair them
to named columns. Optional AUDIT LOG projection requires `Event ID`. Apps Script
checks use a local VM, not a deployed Google runtime. Physical Telegram behavior
and live Sheet layouts remain unverified. Google cannot atomically compare and
write a schema; pause manual structural edits during publication and cleanup.
Local Python is 3.14, not the deployment's pinned 3.12.

## Origination compact UI, typed marks and ID capture - 14 October 2026

The phone/PDF typed-font mismatch was reproduced before changes. New v2 marks
share one server-generated PNG; tests compare its decoded pixels with the image
embedded in the PDF, including all four fonts and long/hyphenated/apostrophe names.
Historical v1 captures retain text rendering; approved copy bytes remain exact.
Optional ID copies are subject-bound, front/back-collated and do not loosen other
evidence or signing requirements. Photo/provider failure and stale identity cases
are covered with synthetic data and mocked storage, never real customer evidence.

Focused local PostgreSQL: 124 passed. Real-template intercepted Chromium:
95 passed at 320/360/390/430/768/1280px, including light/dark screenshots, typed
styles, section arrows, circle radios, participant rows, photo preview and retry.
Screenshots were visually inspected and corrected for inherited header/icon
layout, truncated section names and selected-style contrast. Final screenshots
are under `test-results/origination-accurate-css`; text logs are
`test-results/origination-release-postgres.txt` and `origination-accurate-css.txt`.
Eleven further UI polish checks passed under `test-results/origination-polish-check`.
The first final rerun had one stylesheet-injection failure before app startup;
the harness now removes remote font imports without damaging their semicolon-rich
URLs or the following CSS rules, and the complete rerun passed.

The broader 80-test run had two failures: one assertion still expected mandatory
guarantor copies and was updated for the approved policy, including legacy
retention. The other is an existing repeating-value error-wording mismatch,
reproduced on unchanged HEAD `f0f94663` in an isolated checkout; it is not fixed
here. See `test-results/origination-baseline-failure.txt`. Existing route inventory
issues (33) and unrelated artifact hash mismatches (19) also reproduce unchanged
HEAD. New preview routes are inventoried; four new font hashes verify. Fonts are
new working-tree assets and must accompany the normal commit/deployment. Existing
logo/Portal screenshot pins were not silently changed. JavaScript syntax, Node
contracts, artifact-policy unit tests and Django checks pass; no migration changes.

Physical-device camera/file-picker/keyboard/printing, live Telegram downloads,
SMS and production Drive were not tested. Local Python is 3.14, not the pinned
deployment 3.12. No external writes, new dependency, environment changes,
migrations, production deployment or published-document mutation was performed.
New document publication affects future applications, not captured ongoing ones.

## TAT form/search verification - 14 October 2026

The form alignment and queue branch-search defects were reproduced before the
fix. Six red browser checks measured asymmetric error displacement; synthetic
search inspection distinguished the queue's missing branch match from legacy
Find Case. TAT now opts into shared caption/input/feedback row tracks; other
apps retain their existing layout. Full phone/ID matching and current access,
queue, filters, operational data mode and paging remain enforced.

Focused local PostgreSQL: 16 passed, including identifier formats, branch/BRO
matching, authorization boundaries, deleted/foreign/product/closed-Pilot cases,
filters, APIs and paging. Intercepted real-template Chromium: 83 passed across
320/360/390/430/768/1280px, with light/dark screenshots. Six additional final
report-header checks cover help/close alignment and collapsed specialist controls.
Logs are `test-results/tat-*.txt`; screenshots are under
`test-results/tat-final-20261014` and `test-results/tat-header-final-20261014`.

The broader TAT suite recorded 191 tests with 11 failures/errors. All eleven
also reproduce on unchanged HEAD `a5fa83ea` (190 tests), covering older static
UI contracts and legacy creation/correction/approval fixtures. The broad shared
form browser run's Origination signer-status assertion also fails unchanged
HEAD; it is not a TAT regression. Baseline logs are retained separately. Do not
loosen workflow gates or access policies to satisfy these fixtures.

No production Telegram/Google connection, physical device keyboard or older
non-subgrid WebView was tested. Older WebViews have a single-column layout
fallback. No schema/configuration change or deployment was performed. Reload
the Mini App after the normal approved asset deployment; report/stage/scoring
rules are unchanged.

## Origination signing/copy verification - 13 October 2026

Local PostgreSQL and intercepted Chromium checks cover short acknowledgement
integrity/legacy retention, scoped copy preparation and current-access retrieval,
expired/tampered/stale links, unsigned marking, exact signed bytes, grouped
filters, OTP/staff dates (including Nairobi midnight), replay and date placement.
Browser checks use the real templates/assets with synthetic API data, not an
alternative UI. Mobile/desktop screenshots are under `test-results/playwright`.
Text logs are retained as `test-results/origination-*.txt`.
Final focused PostgreSQL run: 160 passed. Browser run: 90 passed, with widths
320/360/390/430/768/1280 and light/dark examples. Main/remote previews, participant
rows, completion screens and paired alignment were visually inspected. Node
contracts and syntax checks pass; Django reports no model/migration changes.

The unchanged HEAD was tested in an isolated baseline worktree against the same
local PostgreSQL test database. Nineteen existing failures reproduce there:
legacy role-policy fixtures, old product-owned template Admin assertions, and
template calibration fixtures with unsupported field/type mappings. These are
not evidence that this change fixes those separate workflows. The supported
authoring route is the independent Document editor; seed current scoped access
policies before operator testing. Do not loosen authorization to satisfy old
fixtures. Focused affected-domain checks pass separately.
The broader parity run recorded 232 tests and the same 19 baseline failures.
The artifact audit also fails on existing logo/Portal screenshot hash pins; those
files and their allowlist were not changed. Do not silently repin them. See
`test-results/origination-artifacts.txt`. Local Python is 3.14; the pinned
deployment runtime remains 3.12, which was not independently executed here.

Real device Telegram download/keyboard behaviour, live Africa's Talking delivery,
and production Drive retrieval remain unverified; no live SMS, customer data,
provider changes, migrations or deployment were used. Existing published PDFs
do not gain date fields automatically: create an editable copy, save its signers,
review/place the date companions and publish for future applications. Signed
historical PDFs retain their original bytes. This is a controlled application
download/signing change, not a full-repository test certification.

## TAT usability/export verification - 13 October 2026

Synthetic PostgreSQL checks verify canonical BRO corrections, current-access
download links, expiration/tampering, exact calendar capture and personal inbox
paging. XLSX checks inspect values, formats, colours and sample notes rather
than relying on download success text. Browser checks cover 320/360/390/430/768/
1280px, light/dark forms, notifications and native download handoff/cancel/error/
unsupported paths. Screenshots are under `test-results/tat-final-ui` and
`test-results/tat-layout-final`; mobile and desktop examples were inspected.

The reported account-specific empty BRO list has not been reproduced: an IT
actor with active BRO roster fixtures receives the options. Empty/missing helper
states now explain the problem and offer Retry. Check current explicit active
TAT BRO grants and reopen the refreshed app; IT alone is not a BRO assignment.
Actual Telegram native confirmation/device downloads, current customer-account
roster data, Google Sheet formatting and real email-client headers remain
unverified. No real provider call or production data was used.

The first PostgreSQL run reused a database whose migration-seeded catalogue/
audit rows had been flushed by earlier transaction tests. On a fresh isolated
test database, 235/247 TAT checks passed. The remaining six failures/six errors
were reproduced in an unchanged HEAD worktree (12/12): stale asset/copy
assertions, identifier validation expectations and legacy stage-order fixtures.
Focused new tests pass. An existing unrelated Origination signer browser test
still expects old `#sign-status` text instead of the current acknowledgement;
it was excluded from the subsequent TAT/shared-form acceptance run.
The write-route inventory already reports 32 uninventoried existing POST routes;
this change adds no unsafe-method route. Ruff is unavailable locally. These
limitations are not reasons to weaken operational validation or access rules.

Verification records: `test-results/tat-fixes-fresh-django.txt` (247 TAT checks,
12 baseline failures), `tat-baseline-django.txt` (same 12 reproduced at HEAD),
`tat-focused-final.txt` (43 PostgreSQL checks passed),
`tat-report-delivery-final.txt` (128 passed), `tat-presentation-final.txt`
(35 final presentation/audit checks passed), `tat-ui-acceptance.txt` (175 passed),
`tat-final-ui.txt` (66 passed after additional tests/layout refinement), and
`tat-layout-final.txt` (7 passed after the final empty-status alignment fix).
Django check/migration drift, JavaScript syntax, Node tests and whitespace
checks pass. The full repository test suite was not run. Provider/device/inbox
verification must use an explicitly approved target; synthetic browser previews
do not establish delivery or native Telegram behaviour on a real device.

## Complaint email presentation - 13 October 2026

The report layout now keeps the 900px desktop width, compact mobile tiles,
single comparison lines and up to three complementary charts. Charts and tables
have separate rendering slots with unique inline chart IDs. Synthetic Open-case
reports render the age chart once, including populated and empty scopes.

The reported duplicate/clipped age chart in a delivered inbox has **not** been
reproduced from the current renderer. Keep this issue open until the affected
email/screenshot can be compared with its saved HTML and inline attachments.
Already frozen deliveries retain their original payload on retry; a fresh
authorized report capture is needed to see new formatting. Do not erase delivery
evidence or resend automatically to investigate a visual issue.

The apparent short-median/eight-day discrepancy is reproduced: the tile uses
the whole-period median, while chart points use each date's median. Both can be
correct; the report now states this and explains the longest measured resolution.
Missing timing and missing targets have distinct denominator explanations.

Local screenshots cover all three reports at mobile/desktop widths and light/
dark modes under `test-results/email-polish-*`; they do not certify Gmail/Outlook
or dark-mode inversion in a real inbox. No real recipient or external service
was contacted, and no migration/configuration change or deployment was performed.
Verification: 125 PostgreSQL report-delivery tests passed; the final presentation
and fallback refinements passed 57 focused tests and 85 browser tests. Final
screenshots were inspected at 320px and 1280px, including light/dark reports.
JavaScript syntax, Node tests, migration drift and whitespace checks passed.
The full repository suite was not run.
Ruff is not installed in the local virtual environment; focused tests and
JavaScript syntax checks are used, without adding a dependency.

## Placement-driven Origination forms - 13 October 2026

The form now follows valid captured PDF placements plus essential operational
details (ADR 0047). Unpublished alignment edits do not alter forms. Existing
editable drafts retain their own captured document version; use the existing
Change Main LAF/replacement-draft flow to adopt a different published document.
Submitted/signed records are not backfilled. No migration or new setting is needed.

Synthetic PostgreSQL/browser coverage and screenshots are recorded under
`test-results/form-projection-*`. No live Telegram, SMS, Sheets or Drive calls
were performed. Full-repository tests were not run.
Final checks: 154 focused PostgreSQL tests and 46 browser tests passed, with
light/dark mobile and desktop screenshot inspection. JavaScript syntax (127
first-party files), Node tests and migration drift checks passed.

The broader legacy Origination test run exposed seven pre-existing failures:
old Admin upload/wording expectations, a repeated-number validation-message
expectation, and a template-activation fixture with a mismatched document type.
They also fail with the original HEAD service implementations restored in memory;
see `form-projection-baseline.txt`. They are not fixed by this bounded form change.

## Signing and email presentation refinement - 12 October 2026

The current email is up to 900px wide, without an introductory verdict or app
links; this supersedes the 600px presentation recorded below. Graphs, comparison
arrows, target interpretation and attention remain. Real Gmail/Outlook inbox
rendering still requires verification; browser screenshots are not certification.

Signing acknowledgement counts down only after a confirmed signature. Browsers
may refuse automatic tab closure; the saved acknowledgement then tells the signer
to close the tab. Real Telegram WebView closure and production SMS/Drive were not
exercised against customer data. Staff return to their application, not out of
the Mini App. Existing captured completion policies are unchanged.

Focused validation: 175 PostgreSQL tests passed, 103 browser checks passed,
and eight additional email-heading checks passed after mobile screenshot review.
JavaScript syntax (127 first-party files), Node tests and migration drift checks
passed. Full-repository tests were not run. Synthetic screenshots and text logs
are under `test-results/`; no live email, SMS or Drive writes were performed.

## Decision-first email presentation - 12 October 2026

The current 600px management email replaces the earlier 900px layout described
below. Complaint facts supply computed verdicts, safe previous-period comparisons,
actual/mixed targets, low-volume warnings and prioritized aggregate attention.
HTML is bounded to one chart and one five-entry table; complete source datasets
remain in plain text/Excel. Customer identities are not newly exposed in the body.

125 report-delivery/complaint-timing checks passed on isolated PostgreSQL 18
(test-results/management-email-postgres.txt); 80 final affected-module checks passed
in management-email-final-focused-postgres.txt. All 88 browser checks passed
in management-email-browser-complete.txt, including current-access report links,
mobile widths, dark/light emails, chart/settings behavior and TAT task priority.
Another 13 final entry/design checks passed in management-email-browser-last-check.txt.
Screenshots were visually inspected, and a dark table-contrast/logo-background
issue discovered in that inspection was corrected. Node and JS checks passed.
0006 was reversed/reapplied successfully on the owned synthetic database;
makemigrations --check reports no drift. No real email/customer data or external
service mutation was used.

Portal/TAT sources without captured prior-period/exception facts explicitly show
unavailable rather than invented numbers. Open backlog is current, never a
historical reconstruction. Attention links open approved report selections;
case-level names/details remain in the app and Excel. APP_BASE_URL must be set
for app links; links grant no access. Gmail/Outlook actual-inbox inversion and
the full repository suite are unverified. Already-frozen provider retries retain
their previous template; the redesign applies to newly captured deliveries.

## Calendar report cadence and graph axes - 12 October 2026

Yearly is available in each app's shared email settings and Admin. Scheduled
activity reports, Send now and Admin preview cover the last completed Nairobi
calendar period; current open/pipeline snapshots remain explicitly labelled.
Monthly complaint history retains every day, annual history all twelve months.
Graph date labels alone are thinned, not data; dense graphs retain complete HTML
fallbacks. Existing frozen report payloads are never rewritten on retry.

Synthetic evidence is retained in `test-results/email-frequency-postgres-final.txt`,
`email-frequency-browser-final.txt`, `email-frequency-unit-final.txt`,
`email-frequency-node.txt` and `email-frequency-migrations-check.txt`. Monthly
and annual screenshots were visually inspected at mobile and desktop widths.
The initial PostgreSQL run exposed a test-only background-worker/flush race;
the request test now mocks only worker wake-up, retaining authorization and
queue checks. Worker behavior keeps its separate tests; production dispatch
was not changed to accommodate testing.

Apply `python manage.py migrate report_delivery` through `0006_yearly_frequency`.
Rollback metadata to `0005_alter_reportschedule_preset` only after pausing or
reconfiguring yearly schedules; retain delivery evidence when rolling back code.
No production migration/deployment or real email was performed. Actual inbox
rendering and the full repository test suite remain unverified.

## Compact report emails and complaint comparisons - 12 October 2026

The shared 900px email layout and three Complaints schedule choices are
implemented. Existing schedules remain Summary. Period activity, current open
backlog and timing samples have separate, explicit bases; no historical open
backlog is inferred. Previous-period comparisons use Nairobi boundaries and
equal elapsed windows for partial periods. Native one-off Excel filters and
immutable delivery retries remain intact.

All 108 focused report-delivery/complaint-timing tests passed on isolated local
PostgreSQL 18, including authorization, scoped older-case workbooks, target
denominators, period boundaries, capture/retry immutability and provider failure.
Reused-database test fixtures now explicitly create their real audit-chain/policy
rows; no production audit check was bypassed. All 69 focused browser checks
passed. Synthetic email and settings screenshots were inspected at mobile and
desktop widths; checks cover 320/360/390/430/768/1280px, aligned KPI rows,
paired/stacked sections, bounded graph height, blocked images and exact filters.
JavaScript syntax (124 first-party files), the Node suite and migration checks
passed. Migration 0005 was reversed to 0004 and reapplied on the synthetic
database; it changes report choices only, not stored case data or schema columns.

Evidence: `test-results/email-report-postgres-final-pass.txt`,
`email-report-browser-final-pass.txt`, `email-report-js-verified.txt`,
`email-report-node.txt`, `email-report-migration-reverse.txt`,
`email-report-migration-upgrade.txt` and `test-results/playwright/` screenshots.

Actual Gmail/Outlook layout, email-client dark-mode inversion and real inbox
delivery remain unverified. No production migration/deployment, real email or
external data change was performed. The full repository suite was not run.
Apply `python manage.py migrate report_delivery` before deploying the new code;
pause focused schedules/pending deliveries before rolling back to older code
that does not understand their new preset values. See `report_delivery/README.md`.

## TAT and Complaints report/queue polish - 12 October 2026

Focused service/API tests passed on an isolated local PostgreSQL 18 cluster
(122 tests) and SQLite. All 46 focused browser checks passed; they use the real templates/scripts and
synthetic, blocked-network integrations at 320/360/390/430/768/1280px with light
and dark themes. Physical device vibration still needs an on-device Telegram
check; browser tests verify API dispatch/fallback and no duplicate success pulse.
No production assets have been deployed or external data modified.

The expanded history/SLA run has two failures that also reproduce using the
unchanged HEAD timeline implementation, not just this working copy:
`UnifiedTimelineTests.test_case_history_merges_provenance_and_preserves_redacted_event_shell`
and `HybridTatAndEscalationTests.test_daily_snapshots_are_idempotent_reporting_projections`
in `core.tests_workflow_history_sla`. Evidence is retained in
`test-results/ui-baseline-history-check.txt`; these are not suppressed or claimed
as passing. The full repository suite has not been run in this pass.

## Configurable Origination signing - 12 October 2026

Implemented the opt-in `all_required` policy: product defaults, document-owned
participants/placements, Superuser application overrides, officer submission
and deliberate link dispatch, parallel individual signatures, and transactional
approval by the final required signature or stamp. Existing applications keep
their captured approval policy. A matching compliance-approved consent policy
is required; no product, consent or grant is activated by the migration.

Migration 0007 adds the bounded participant table and nullable legacy-compatible
session/action references. Synthetic PostgreSQL upgrade/reversal tests retain
old packet bytes, policies and bearer-session evidence. Reversal is documented
in ADR 0045 and the Admin guide; do not drop new evidence without an explicit
backup/recovery decision. No cron, provider replacement or lending formula change.

The focused PostgreSQL run passed 169 tests without skips, including concurrent
final-signature retries, two borrowers/two same-role staff, required stamps,
unchanged-save preview validity, authority, withdrawal, render failure, typed
value contracts and scoped deletion. A final 23-test signing-plan run also passed,
including the added officer queue regression: unsent/expired links stay actionable
after the officer signs. The broader setup/editor/catalogue run
passed 154 of 157 tests. Its three failures also reproduce on unchanged HEAD
`e8928314`: grouped security-value repair, an older reusable-document Admin-copy
label, and a duplicate requisition-number index. They are not suppressed here.

All 48 selected browser checks passed. The 17 signing-specific checks were rerun
after the final compactness changes. Actual templates/scripts and synthetic local
responses cover 320/360/390/430px, desktop, light/dark Mini App themes, searchable
Admin assignments and saved-signature recovery after SMS failure and refresh.
Mobile Admin, pending/approved staff, and recipient screenshots were inspected.
JavaScript syntax, the Node suite, Django checks and migration checks passed.

The tracked-artifact audit still reports the same 19 logo/screenshot hash
mismatches as the unchanged HEAD worktree. No assets, allowlist exceptions or
customer data were added. Evidence is in `test-results/signing-plan-final-postgres.txt`,
`signing-plan-regression-current-postgres.txt`, `signing-plan-baseline-postgres.txt`,
`signing-plan-baseline-index.txt`, `signing-plan-browser-final-verified.txt`,
`signing-plan-queues-final-postgres.txt`, `signing-plan-browser-signers-final.txt`,
and the Playwright screenshot directory.

No production migration/deployment, real SMS invitation/OTP, Telegram delivery
or Drive archival was performed. Full-suite and live-device acceptance remain
unverified. Review the new product/document/consent configuration before enabling
the simplified policy for new applications.

## Origination field rules and country choices - 9 October 2026

Main and supporting documents now share typed controls and server validation,
including repeating cells. New reviewed schemas use active country choices,
integer counts/years, email/date rules and explicit county/sub-county bindings.
The document editor can remove rules and make ordinary fields optional. Shared
fields remain required when another selected document needs them; the form
explains this. Existing font/spacing and inline-only errors are retained.

No migration or new persistent model is needed. Published canonical keys/types,
application snapshots and frozen signed values are not rewritten. Review changes
in an editable document version, publish it, and use that version for new
applications. Nationality adopts replacement choice keys; old text keys survive.
PDF placements are human-reviewed, not automatically guessed or published.

Verification used synthetic fixtures and a separate local PostgreSQL 18 cluster:
112 focused tests passed, with no skips. The additional existing template/Generic
seed suite ran 65 tests: 60 passed, three failed and two errored. All five failures
reproduce on unchanged HEAD `f7bb59b7`; they concern older product-owned Admin
upload expectations and an empty supporting-document publication fixture.
No new regression was found. All 42 focused browser checks passed, including
320-430px forms, desktop controls, both Mini App themes, inline errors, drafts,
supporting fields and independent person/location dropdowns. Screenshots and a
rendered synthetic PDF were visually inspected. JavaScript syntax and the Node
suite passed; Django checks and migration checks passed.

The tracked-artifact audit still reports 19 existing logo/screenshot hash
mismatches. The findings are identical in the unchanged HEAD archive; this
change does not alter those assets or relax their allowlist.

Evidence is under `test-results/`: `origination-field-validation-focused-final.txt`,
`origination-field-validation-browser-final.txt`,
`origination-field-validation-regression.txt`,
`origination-field-validation-baseline.txt`,
`origination-field-artifact-baseline.txt`, `origination-fields-final/` and
`origination-field-validation/`. Full-suite, live Telegram device verification
and deployment remain unverified. No production records or integrations changed.

## Selected testing deletion across Mini Apps - 9 October 2026

Completed the shared selected-deletion action for reviewed Origination, Portal,
Complaints, TAT and SPIN Admin models. It is disabled by default and requires
`MINIAPP_TEST_DELETION_ENABLED=True` plus an active Superuser. Configuration can
keep linked operational history; deleting selected evidence includes its owning
workspace, disclosed in the confirmation. No mandatory note is added.

Exact impact fingerprints, current row locks, actor-bound retries and independent
compliance evidence protect deletion. Unknown links and stale confirmations block
the whole transaction. Shared identities/access grants, raw ingestion, Drive files
and captured recognition facts survive. Deleted finance claims remain consumed.
Sheet cleanup is DB-first, starts in a bounded server background task, and can be
retried through Integration operations. There is no cron or browser dependency.

Verification used synthetic data, a separate local PostgreSQL 18.6 cluster and
mocked Google integrations. All 99 focused deletion, finance and real-browser
tests passed on PostgreSQL with no skips. The affected existing workflow suite ran 394 tests:
381 passed, seven failed and six errored. The exact same 13 test failures reproduce
in an isolated worktree at unchanged HEAD `43974c63`; no new failure was introduced.
An initial reuse of a flushed test database also lost migration-seeded fixtures;
fresh database runs were used for the final comparison.

The real Admin selection/confirmation journey passed at 320, 430 and 1280px in
light/dark themes; screenshots were inspected for wrapping and overflow. JavaScript
syntax passed for 120 files, affected Python compiled, Django checks passed and
`makemigrations --check --dry-run` reported no missing migration.

Evidence: `test-results/miniapp-deletion-focused-postgres.txt`,
`test-results/miniapp-deletion-regression-postgres.txt`,
`test-results/miniapp-deletion-baseline-postgres.txt`,
`test-results/miniapp-deletion-js.txt`, and
`test-results/miniapp-deletion-live/`.

Apply payments.0008 and requisitions.0005 before enabling the setting. See
[the operator instructions](docs/origination-admin-guide.md#selected-testing-deletion-across-mini-apps)
and [ADR 0044](docs/adr/0044-selected-miniapp-testing-deletion.md) for ownership,
numbering, retry and safe rollback boundaries. Missing immutable Sheet IDs require
repair; no name/phone/row guess is made. No real customer record, production Sheet
or Drive file was removed. Live provider cleanup, full-suite validation, deployment
and physical Telegram devices remain unverified.

## Published LAF attachment in guided setup - 9 October 2026

Fixed the circular chooser rule that hid published documents until they were
already assigned to the product. Explicit attachment now retains the original
published document and alignment, validates compatibility transactionally and
does not silently create an unpublished copy. An empty allowlist still grants
no application availability; the catalogue explains it as "No products assigned".
Selected cards update after confirmed autosave without requiring refresh.

- The original missing-document reproduction failed before the fix and passed
  afterward; its regression coverage is now checked in.
- All 95 focused tests passed against a separate local PostgreSQL 18.6 cluster,
  with no skipped tests. This includes simultaneous first attachments, retries,
  permission denial, incompatible-selection rollback, immutable application
  snapshots, guided publication and the existing document authoring/maintenance
  browser journeys. The initial focused SQLite run also passed all 91 tests.
- Real Admin screenshots at 320, 430 and 1280px include light/dark views. The
  chooser, immediate selected cards, catalogue label and published Product
  were checked; mobile light/dark screenshots were visually inspected.
- First-party JavaScript syntax passed for 119 files; affected Python files
  compile and `git diff --check` passes.

Text evidence: `test-results/origination-attachment-postgres.txt`,
`test-results/origination-attachment-tests.txt` and
`test-results/origination-attachment-js.txt`. Screenshots:
`test-results/origination-attachment-live/`.

No deployment or production-data change occurred. No migration, setting or
external dependency is required for this attachment fix. After deployment,
open the Product's Documents task, select the published LAF, wait for Saved,
then publish the Product when its tasks are ready. Do not recalibrate the same
published PDF merely to attach it. The full repository suite, real provider
delivery and physical Telegram devices were not exercised in this change.
The separately completed cross-Mini-App deletion work is documented above.

## Origination testing, bootstrap and selected deletion - 9 October 2026

Implemented non-blocking deployment setup warnings, provider-configured OTP
availability, opt-in one-time release seeding of eleven private blank LAFs, and
Superuser-only permanent selected-product/Origination deletion. Authentication,
consent integrity, OTP verification/limits and independent approvals remain
enforced. No new model, migration, scheduler or simulator was introduced.

Verification used isolated SQLite, synthetic records and mocked integrations:

- The focused acceptance run completed 121 tests: 119 passed and two
  PostgreSQL-only concurrent-first-request tests were skipped.
- The real local Admin confirmation passed at 320, 430 and 1280px in light and
  dark themes, including Cancel, a protected selection and confirmed deletion.
  Final 320px light and 1280px dark screenshots were visually inspected after
  fixing the confirmation buttons' touch targets and focus states.
- All eleven sanitized PDFs retain pixel-identical rendering across 25 pages;
  author/XMP metadata and filled-widget checks pass. The blank bundle contains
  no customer submissions and is not exposed through static-file URLs.
- Seven artifact-audit unit tests and syntax checks for 118 first-party
  JavaScript files pass. Migration inspection reports no changes.
- An additional 43-test regression run had 39 passes, one PostgreSQL-only skip,
  and three existing failures: two BM permission/notice fixtures and the
  environment-template line-count assertion. They were reproduced with the
  previous signing/dispatch functions and unchanged environment template.
- Five older template-lifecycle/Admin tests also fail with the previous upload
  implementation; their product-owned assumptions or missing supporting schemas
  predate this change. These unrelated tests were not rewritten to pass.
- The new blank assets pass privacy/hash checks. The repository-wide artifact
  audit still reports 19 existing hash mismatches in the unchanged logo and
  Portal screenshot fixtures; the same mismatches are present in HEAD.

Text evidence is retained in ignored
`test-results/origination-plan-acceptance.txt`,
`test-results/origination-plan-browser.txt`,
`test-results/origination-plan-additional-regression.txt`,
`test-results/origination-existing-template-baseline.txt`,
`test-results/origination-existing-additional-baseline.txt`,
`test-results/origination-plan-privacy.txt` and
`test-results/origination-plan-migrations.txt`.

PostgreSQL locking/concurrency, real SMS delivery, physical Telegram devices and
the full repository suite remain unverified. No deployment, live seed upload,
external file deletion or real product deletion occurred. Enable the two gates
deliberately; bootstrap uses the existing release command and seeds unpublished,
unassigned drafts only. Alignment, signer/legal review and publication are still
human-owned. Permanent deletion cannot be undone through the app. Already-started
external requests cannot be recalled; subsequent queued dispatches skip deleted
Origination sources, while compliance history and external files remain intact.

## Canonical Origination values - 8 October 2026

Implemented explicit version-2 shared/document field meanings, scoped inputs,
allowlisted calculations, exact frozen document contexts, person-role reuse,
compatible selection and non-truncating rendering. Legacy applications are not
backfilled. Six supporting-LAF seeds remain unpublished and unassigned drafts.
Migration `origination.0006_originationdatafield_value_contract` is additive and
has only been exercised in isolated test databases, not a deployed database.

Verification used synthetic local fixtures and mocked external integrations:

- All 45 focused value-contract and supporting-seed tests pass, including a real
  signing-package freeze, rollback, identity separation, actor-bound retries,
  document deselection, retained financial-input exclusion and row-capacity checks.
- The broader 199-test regression run had 197 passes, one PostgreSQL-only skip
  and one existing Admin-label assertion failure. The unchanged published-document
  template says "Published document"; the assertion still expects "Published
  reusable document". That unrelated label/test was not changed.
- All nine Node suites and syntax for 118 first-party JavaScript files pass.
- The real Admin custom-PDF browser journey passes: upload, signer pack/edit,
  field meanings, placement, preview, publication and explicit Product attachment.
  Screenshot coverage includes 320, 390, 430 and 1280px; 320px field meanings,
  390px dark mode and desktop preview were visually inspected.
- All 10 Origination Mini App browser checks pass, covering queue widths,
  navigation, native validation and shared/local inputs. Final supporting-document
  screenshots at 320px were visually inspected in light and dark mode.
- Text evidence is retained in ignored
  `test-results/origination-value-contract-acceptance.txt`,
  `test-results/origination-value-contract-regression.txt`,
  `test-results/origination-value-contract-browser.txt` and
  `test-results/origination-value-contract-migrations.txt`. Synthetic Admin
  artifacts are under `test-results/origination-authoring/`.

The complete occurrence-by-occurrence register across the eleven paper PDFs is
not visually certified. Ambiguous paper fields and native legal signer roles
still need business/compliance review and real PDF placement checks; passing
seed hashes does not certify a document for legal use. Actual disbursement,
receipt collection, company applicants and arbitrary guarantor counts are not
introduced by this change. PostgreSQL parity, physical Telegram devices,
screen-reader verification and the full repository suite remain unverified.
No production deployment, live seed application or real external writes occurred.

## Complaints report controls and date cohorts - 8 October 2026

Implemented the Specific Quarter filter, compact chart-type icons, automatic
chart selection, selection feedback above search, and a five-card KPI row.
Date Type affects cards/table only; graphs retain their intrinsic date bases.
Reported vs resolved counts each reported complaint once under its current
Closed or Open & Reopened status, rather than counting repeat closures.
Complaint duration labels include hours/days; graph dates use dd-mm-yy across
Complaints, TAT and Portal without changing table dates or ISO filter keys.

Verification used synthetic local fixtures and mocked integrations:

- 75 focused Playwright checks pass, including real graph clicks, dropdowns,
  quarter selection, grouping/type alignment, keyboard paths and export parity.
- 186 focused Django tests completed: 185 passed and one PostgreSQL-specific
  test skipped on isolated SQLite. Coverage includes timing, register access,
  complaints and report delivery. A fresh migrated test database resolved the
  missing seed rows caused by reusing a previously flushed test database.
- All nine Node suites and syntax checks for 118 first-party JavaScript files pass.
- Screenshot coverage includes 320, 360, 390, 430, 768 and 1280px in both themes.
  Final 320px chart controls/quarter filters and mobile/tablet/desktop report
  screenshots were visually inspected. Artifacts remain under the ignored
  `test-results/playwright/` directory and are replaced by later browser runs.

PostgreSQL parity, physical Telegram devices, assistive technology and the full
repository suite remain unverified. No production deployment or real external
integration writes were performed. No migrations, settings or dependencies changed.

## Shared controls, media and TAT chart selection - 8 October 2026

Implemented shared native primary-action ownership, compact draft recovery,
right-aligned correction/status controls, fixed media zoom/pan and scoped chart
point selection. Form typography, workflow transitions and authorization remain
unchanged. Historical workload snapshots cannot identify their original cases;
clicking them explains this limitation instead of showing today's unrelated cases.

Verification used only synthetic local fixtures and mocked integrations:

- 80 focused Playwright checks pass, covering native-button validation/fallback,
  unavailable complaint types, real select taps/keyboard input, dependent locations,
  image corners at three aspect ratios, preview cleanup, chart series selection,
  historical totals and existing form/report/navigation regressions.
- 44 focused Django/report-email checks pass on isolated SQLite, including scope,
  distinct cohorts, measurement denominators and matching Excel/email filters.
- All nine Node suites and syntax checks for 118 first-party JavaScript files pass.
- Screenshot checks cover 320, 360, 390, 430, 768 and 1280px in both themes.
  Final mobile/tablet/desktop Complaint and TAT screenshots and a zoomed photo
  corner were visually inspected; the tablet draft-retry alignment was corrected.
- Text logs: `test-results/miniapp-controls-browser.txt` and
  `test-results/miniapp-controls-backend.txt`. Synthetic screenshots remain under
  `test-results/playwright/` (a later Playwright run replaces that output).

The original Complaint Type "does not open" symptom was not reproduced in local
Chromium: native tap/keyboard selection works in the real form shell. Catalogue
unavailability now has an explicit recoverable state; this is not proof of the
original device-specific cause. Physical Telegram Android/iOS picker, keyboard
and pinch behavior, assistive technology, PostgreSQL parity and the full repository
suite remain unverified. No production deployment or real integration writes were
performed. See `docs/miniapp-ux-parity-notes.md` for the shared component contract.

## Independent Origination authoring - 8 October 2026

Product setup now has three non-linear tasks: Details, Lending terms and Documents.
The independent Document editor owns PDF, signers, fields, placement and preview.
Both save drafts with server-confirmed feedback and have one Publish action each.
Product publication never publishes a document. Shared edits and product-only
copies preserve existing applications and their exact signing snapshots.

Verification completed with synthetic local data and mocked integrations:

- 71 focused Django checks pass, including two real localhost browser journeys.
  A subsequently added published-copy retry regression passes separately.
- Seven focused Playwright layout checks, all nine Node suites and JavaScript
  syntax checks (116 files) pass. Django checks pass; no migration drift.
- A custom PDF was uploaded, signers added and edited, lending fields added,
  nine fields/signatures placed, the rendered preview checked and the document
  published. The draft product was then linked and published without a dead end.
- Screenshots were inspected at mobile and desktop sizes, including dark mode.
  Published documents remain read-only while the mobile panel can still close.
- The before-change evidence is a synthetic post-upload editor checkpoint,
  not a recording of the entire original upload journey.

The broader fresh-database selection is not fully green: 183 of 188 tests pass.
The remaining three failures and two errors were reproduced against unchanged
HEAD Python code. They concern older template-admin expectations and an incomplete
supporting-document fixture, not the new independent-authoring flow. Evidence:
`test-results/origination-workspaces-final.txt`, `origination-copy-retry.txt`,
`origination-workspaces-fresh.txt` and `origination-baseline-check.txt`.
Screenshots and the final trace are under `test-results/origination-authoring/`.

Backend verification used isolated SQLite. PostgreSQL row-lock and concurrency
parity, production Python 3.12, physical Telegram devices and the full repository
suite remain unverified. Ruff/Black are not installed locally. No new models,
migrations, dependencies, settings, production deployment or real integration
writes were involved. See `docs/origination_product_setup_workspace.md`.

## Form presentation correction and Portal camera - 8 October 2026

Restored the existing per-app form text and control scale; validation now uses
inline errors and first-field focus without a repeated top list. Non-field
failures remain visible as one notice. Restore is green and Discard red in both
themes. Required markers, input preservation, recovery and workflow rules remain.

The inert Create lead camera was reproduced: media listeners were installed only
inside existing-case recovery. Camera/gallery/preview/removal now have separate
wiring for both new and existing cases. Synthetic tests cover ID/LAF/supporting
captures, one reused stream, permission denial, unsupported cameras and file picks.

57 focused Playwright checks pass, plus the existing full camera flow (58 total).
JavaScript syntax and all nine existing Node suites pass. Mobile/desktop screenshots
were inspected, including inline errors, both draft themes and the camera overlay.
Browser log: `test-results/forms-correction-browser.txt`.

The full repository suite and PostgreSQL tests were not rerun for these frontend-only
changes. Earlier broad-suite gaps below remain separate. Physical Telegram camera,
keyboard and screen-reader verification remains required. No migrations, new settings,
production deployment, customer data or real integration writes were involved.

## Shared Mini App forms verification — 8 October 2026

The shared submission-time validation, accessible error summaries and field-only
Complaint/TAT creation recovery were verified with synthetic local fixtures.
44 focused Playwright checks pass, including the actual Origination signing
template and Portal decision forms. Mobile screenshots were inspected; required
marker placement, field alignment and readable error text were corrected.
76 focused Complaint/draft backend tests pass on isolated SQLite. JavaScript
syntax and the existing Node suite pass.

The full browser run is not green: 399 passed and 9 failed. Eight failures were
reproduced against unchanged HEAD: obsolete camera text, complaint chart fixture
visibility, invoice iframe expectations and the superseded Prepare-order button
contract. The ninth was a fractional-pixel assertion; its corrected check passes
in the focused run. A broader backend selection also has an existing Complaint
asset assertion expecting the retired “Received vs resolved” label.

PostgreSQL transaction parity, physical Telegram WebViews, real screen-reader
sessions and real autofill/voice services remain unverified. No production data,
external integrations, schema or workflow permission changes were made.

## Portal agreement and preview verification — 6 October 2026

85 focused SQLite backend tests pass for agreement acceptance/retry, changed
identity, review flags, revoked/superseded corrections, financial holds,
disjoint invoice queues/counts, payment membership, letter rendering and scoped
reset cleanup and permission-checked signed-scan previews. Evidence:
`test-results/portal-agreements-tests.txt`.

64 Playwright checks pass with actual Portal components/styles and synthetic
offline API/Telegram data: pinch versus swipe, PDF page navigation, late-view
cleanup, retained receipt-origin search, attested file upload, named downloads,
320–430px mobile, 768px and 1280px layouts. Screenshots were inspected at 320px
and 1280px; Close icon sizing and wrapping action labels were corrected.
Evidence: `test-results/portal-media-browser.txt`; 19 further Portal media and
Complaints compatibility checks pass in `test-results/portal-media-final-browser.txt`.

Node checks and JavaScript syntax pass; migration checking reports no drift.
Logs: `portal-agreements-node.txt`, `portal-agreements-javascript.txt`, and
`portal-agreements-migrations.txt` under `test-results/`.

PostgreSQL lock/concurrent-acceptance tests and physical Telegram-device
verification are not run. The full repository suite is not claimed green;
earlier documented broader-suite failures remain separate. No production
migration, payment execution, Drive/Sheets write or real notification was made.
The new migration must ship with the code before signed agreements are used.

## Portal Operations verification — 6 October 2026

Focused backend checks cover order preview/append/cancel/reuse, exact signed
versions, protected invoice/payment evidence, SysUp choices and retries,
Operations policy repair, physical sign-off and configuration-scoped reset.
The latest complete focused run has 165 passing tests; final guard results are
in `test-results/portal-operations-focused.txt`.

42 Playwright checks pass using actual Portal modules and the production shell
stylesheet cascade with synthetic, offline API/Telegram fixtures. Screenshot
review covers 320, 430, 768 and 1280px order actions, invoice records, deliveries
and SysUp field review. This caught and corrected action heights, duplicated
SysUp headings, Close icon rendering and animation-time screenshot captures.
Evidence: `test-results/portal-operations-browser.txt` and
`test-results/playwright/portal_operations_workspac-*/`.

JavaScript syntax and Node checks pass; migration checking reports no changes.
Logs: `portal-operations-javascript.txt`, `portal-operations-node.txt` and
`portal-operations-migrations.txt` under `test-results/`.

The broader 302-test SQLite selection is not green: 31 failures and one error
remain in `test-results/portal-operations-python.txt`. It includes already
documented retired-route/report expectations, old automatic daily-order merge
contracts now superseded by explicit append, unsigned invoice fixtures, and
payment-document fixture failures. Not all failures have been independently
classified against unchanged HEAD; do not claim the repository suite passes.
The six pre-existing document-button geometry failures remain documented below.

PostgreSQL row locks, concurrent transactions, migrations/rollback on a copy of
the production schema, real Telegram and Google integrations remain unverified.
The local PostgreSQL test account was not available with usable credentials;
these backend runs used isolated SQLite. Before release, run the configuration-
scoped legacy finance audit and PostgreSQL checks described in ADR 0039.
Unowned legacy documents need explicit ownership review. Completed historical
payments are never auto-repaired or deleted to satisfy new signed-order gates.

## Invoice transport verification — 6 October 2026

The slow-upload and missing-authentication symptoms were reproduced with the
actual Portal modules and synthetic browser fixtures, then fixed. Invoice upload
does not use the browser's ordinary 20-second timer: the browser awaits the
server/network outcome while the upload button remains busy. This does not turn
parsing into a durable background task; closing the app or losing connectivity
can still lose the response. Check Recent uploads before retrying in that case.

27 related browser checks pass, including eight new transport regressions.
JavaScript syntax and all Node checks pass. Synthetic mobile screenshots were
inspected for upload feedback and invoice previews. No real Telegram device,
production invoice, Google integration, deployment or database suite was used
for this frontend-only change.

Six existing `portal_finance_actions.spec.js` document-button geometry checks
fail at 320/360/390/430/768/1280px (40px instead of the expected 44px). All six
also fail in an isolated, unchanged HEAD archive. Baseline evidence:
`C:/Users/Administrator/AppData/Local/Temp/portal-invoice-transport-baseline-e14f11a9ab6042ada90b9779f0898450/baseline-results.txt`.
They are excluded from the passing 27-check selection, not silently marked green.

## Portal role-workflow verification — 6 October 2026

113 focused backend tests and 87 browser checks pass. JavaScript syntax and all
Node checks pass; migrations report no uncommitted model changes. The backend
log is `test-results/portal-remediation-focused.txt`, and synthetic screenshots
are under `test-results/playwright/`. Apply core.0201 as documented in CHANGELOG.md.

The broader SQLite selection still has 25 failures and one error. An isolated
archive of unchanged HEAD reproduces exactly the same failing test names across
192 existing pipeline tests. These include retired route expectations and invoice
fixtures without finalized requisitions. Current evidence is in
`test-results/portal-remediation-django.txt`; baseline evidence is in
`C:/Users/Administrator/AppData/Local/Temp/portal-remediation-baseline-100512ad44094ada8dd2e3e6163015a7/baseline-tests.txt`.
Do not interpret focused passing checks as a fully green repository suite.

Local browser fixtures use the actual Portal markup, modules and stylesheet cascade
with synthetic API/evidence responses. Screenshots are checked at 320–430px,
tablet and desktop in light/dark themes. Real Telegram device camera permissions,
native PDF scrolling/gestures, map coverage and live voice-provider/Drive cleanup
remain authorized operator checks. Existing external Maps fallback remains available.
PostgreSQL and production integrations are not exercised by these SQLite tests.

## Report email client rendering — 5 October 2026

Browser screenshots use synthetic captured reports and substitute embedded
Content-ID images with data URLs for local preview only. They verify layout,
not actual Gmail/Outlook Content-ID handling, font fallback, or automatic dark
mode. Verify new emails in authorized test inboxes before broad rollout; no
live emails are sent during local tests. Report tables remain available when
images are blocked or dense charts cannot be drawn legibly. Retried frozen
emails deliberately keep their original typography and attachments.

## Portal density validation — 5 October 2026

The isolated SQLite pipeline selection is not green. A comparison with HEAD
backend modules reproduced 25 failures and one error across 192 existing tests,
including stale screen-route expectations, invoice fixtures missing official
requisitions, preview availability and legacy generation assertions. Logs:
`test-results/portal-density-baseline.txt` and `portal-density-backend.txt`.
The current 215-test selection has exactly the same failing test names.
Do not treat the focused passing tests as full pipeline certification; use the
current supported routes and finalized-order fixtures for manual verification.

The new reason/source-row and affected approval/location/draft checks pass
(26 tests). The combined 72 browser layout/interaction checks pass using synthetic
fixtures, including narrow widths, dark themes, source paging and report controls.
PostgreSQL, device Telegram WebView and live Sheets/Drive are not verified.
The local Python environment is 3.14 while the project targets 3.12; Ruff is
not installed locally. Run the pinned CI environment for release certification.

## Immediate report sending - 5 October 2026

Send now wakes a bounded worker after commit; it no longer relies on an operator
running a command. Pending work survives restarts in Django and is woken on
Settings/status requests. This is best-effort process-local execution, not an
always-on scheduler: unattended recurring reports and retries while no one uses
the app still need the existing runner. Provider acceptance is distinct from
verified delivery. Local validation passed 49 backend and 11 browser tests with
synthetic data/mocked Resend; live inbox delivery and local PostgreSQL execution
have not been verified in this session.

## Workflow-owned email settings - 5 October 2026

Portal, TAT and Complaints now provide IT-only schedule and recipient settings
for their own reports. A fresh isolated SQLite selection passed 78 backend
tests; the focused browser selection passed 15 tests, including mobile widths
and Complaints Settings navigation. PostgreSQL concurrency and real Resend
delivery remain unverified; sending remains off by default.

An additional broader selection exposed an existing clock-sensitive Complaints
timing fixture: it fixes case dates at 2 October but evaluates ages against the
current date. Its expected age bucket no longer holds on 5 October. This is not
a passing test and was not silently changed as part of email settings.

## Scheduled Portal email rollout - 5 October 2026

Resend delivery is disabled by default. Local checks use synthetic cases and
mocked provider responses; they do not establish verified-domain DNS, inbox
delivery, production webhook reachability or scheduler operation. Configure
and verify these using [the operator steps](report_delivery/README.md) before
enabling sending. PostgreSQL lease/isolation parity has not been run in this
session because no local `TEST_DATABASE_URL` was configured; use the existing
PostgreSQL test runner before production rollout. No production migrations or
real report emails were sent.

## Complaints, TAT and Portal depth review - 3 October 2026

See [the focused implementation review](docs/miniapp-depth-review-2026-10-03.md)
for source locations, reproduction details, test selections and failure
classification. Python 3.12.10, the pinned Python dependencies, Playwright
1.62.1 and Chromium are now installed locally. This supersedes the initial
source assessment's unavailable-runtime limitation below.

- Reproduced a TAT report authorization defect: its queryset combines scopes
  from grants that do not authorize reports. Report access must retain the
  capability and scope of one complete eligible grant.
- Reproduced an empty Portal case queue for group-scoped staff even though
  individual case permission allows their owned case. The central queryset
  omits the group relation required by the generic scope resolver.
- Reproduced complaint file-selection loss after a failed finish-created
  upload, Pending cursor traversal dropping newer rows, and changed TAT retry
  payloads returning unchanged state as successful receipt replays.
- The full browser suite ran 186 tests: 185 passed and one stale Complaints
  report fixture failed. The fixture lacks the current report summary/module
  contract and assumes two chart slides; the current report has eight.
- Two broad isolated SQLite backend selections ran 960 tests. Initial results
  were 12 failure entries/6 errors/2 skips and 25 failure entries/3 errors/3
  skips. Two logging failures came from the diagnostic harness and passed after
  correcting it. Other failures/errors remain classified in the review.
  Selected complaint modules had no failure/error entries; their concurrency
  check was skipped. No PostgreSQL concurrency success is claimed.
- Four focused synthetic database reproductions and the additional Node
  finish-upload probe passed by asserting the observed defects. These are
  reproduction results, not evidence of fixes.
- System checks, migration drift, migration graph, architecture boundaries,
  dependency parity, Python compilation and package consistency pass. The
  official write inventory fails with 27 routes; environment-template parity
  fails with 116 entries; the dependency exception expired before audit runs.
- Local Node 26 is outside the repository's supported range, and Windows
  Pango is absent, so native WeasyPrint import/layout is not verified. No live
  Telegram/Google integration or production resource was changed.

## Cross-workflow source assessment — 3 October 2026

See [the codebase assessment](docs/codebase-review-2026-10-03.md) for the
reviewed commit, source evidence, functional map and priorities. This was an
analysis session; application behavior and production resources were not changed.

- Legacy message deduplication hashes sender/content/time without group context.
  Identical inputs in separate groups can share a globally unique processing
  key. No production incident was reproduced. Review the intended scope and
  historical retry compatibility before changing the key.
- Unparsed invoice pages can log a 300-character document-text preview. Avoid
  treating ordinary logs as sanitized evidence; review access/retention and
  replace content diagnostics in a separately scoped fix.
- Legacy deposit fallback parsing uses `float` before document preparation.
  Canonical product quotes use Decimal; this finding does not establish an
  incorrect payment. Review fallback normalization and output compatibility.
- Database catalogue/checker app-label lists do not cover all installed local
  apps. QA models are outside the checked-in catalogue, and the additional
  bounded-model metadata checks omit the installed extracted-app labels.
- Legacy unbound Telegram profiles can retain username-based initial binding
  without activation proof. Review eligible enrollments before changing the
  identity contract. Atomic rejection tests also deliberately retain no raw
  intake rows; clarify rejection-evidence policy separately from case creation.
- The dependency exception expired on 30 September. A supplemental source
  cross-check identified 28 write-route inventory candidates; the official
  Python checker and a fresh dependency audit were not run in this shell.
- Fresh JavaScript syntax checks passed for 91 files, all nine Node test groups
  passed, and all seven tracked Apps Scripts passed syntax checks. Python
  discovery was retried but found only Windows Store aliases. Playwright was
  unavailable. No fresh backend, browser, PostgreSQL, migration, restore or
  live-integration success is claimed.

## Portal shared controls verification - 2 October 2026

- The focused PostgreSQL inbox/dashboard suite passes all 18 tests; JavaScript
  syntax and all nine Node test commands pass. No migration is generated.
- All 77 Portal browser tests pass on the final implementation without
  updating baselines. Results: `test-results/portal-shared-controls-browser.txt`;
  database results: `test-results/portal-inbox-postgres-final.txt`.
- Full-shell visual fixtures use synthetic API responses, not a live Django
  page/Telegram session. Browser coverage checks mobile/desktop geometry and
  light/dark themes. Linux CI rendering and production behavior are not yet
  verified by this local Windows run.
- Reviewed synthetic visual baselines are SHA-256-pinned. The tracked-artifact
  audit cannot count these new files until they are added to Git. Separately,
  HEAD already has a logo hash mismatch: `jawabu-logo.png` is `23a08f62...`
  while the existing allowlist expects `06c1d7e3...`. This unrelated asset was
  neither replaced nor re-approved by this UI change.
- Inbox responses are paginated, but their scoped task list is assembled in
  memory before pagination. Very large workloads may warrant a separately
  measured server-side task-query optimization; no new persistent inbox model
  has been introduced here.

## Complaints unified history verification - 2 October 2026

- Fresh PostgreSQL run: 94 tests, 92 passed, two failures. The local ignored
  log is `test-results/complaint-history-postgres-fresh-final.txt`.
- `test_customer_id_is_digits_only_and_preserves_leading_zeroes` expects
  "numbers only" while the unchanged validator says "1 to 9 digits only".
- `test_compact_two_state_workspace_has_only_supported_actions` expects the
  old `[0-9]*` template pattern. HEAD already uses `[0-9]{1,9}`; later assertions
  also contain outdated input labels and asset versions. These unrelated tests
  were not weakened to obtain a green suite.
- Browser feedback/draft/voice/queue regression, nine Node groups, JavaScript
  syntax and migration checks passed. Screenshots were inspected. No live
  Telegram or Google integration was exercised.
- Old history without immutable affiliation evidence is labelled Staff, not
  guessed from current grants. Existing Sheet comment cells change format on
  their next successful synchronization, not through an automatic bulk rewrite.

## Portal compact controls verification - 2 October 2026

The focused document-signoff/payment PostgreSQL suite passed 77 tests using
synthetic data and mocked integrations. Scan replacements retain previous bytes
and preserve workflow progress; preview scope and removable-duplicate selection
have regression coverage. No production Google/Telegram integration was called.
The 59 selected browser tests passed, including compact finance layouts,
notification scrolling, phone links and nested navigation. Performance screenshots
were manually inspected at 320px after the compact-height correction.

The wider `core.tests_pipeline` PostgreSQL run is not green: 192 tests ran with
25 failures and one error. Evidence is in the local ignored artifact
`test-results/portal-pipeline-postgres.txt`. Failures include outdated-client 426
responses, stale shell assertions and invoice fixtures without official orders.
This pass has not independently reproduced those failures on unchanged HEAD;
do not classify all of them as unrelated or claim a full-repository pass.

Duplicate removal is operational soft deletion, not evidence erasure. Payment
receipt, payment-history and identity-change references remain protected. Real
Drive movement and dialler handoff inside Telegram still need deployment smoke tests.

## Portal engineering remediation — 2 October 2026

Local prevention/recovery changes cover EQ-01/02/03/04/05/07/08/09/10/12.
EQ-06 (invoice diagnostic privacy) and EQ-11 (broad refactor) were excluded by
the user and remain open. See the implementation table in
[the remediation plan](docs/portal-engineering-remediation-plan-2026-10-01.md).

Focused PostgreSQL verification now includes real separate-connection claims,
fresh migrations and a representative prior payment schema upgrade. The earlier
197-test PostgreSQL selection and final 199-test run passed.
The 134 browser tests and nine Node groups passed. These are scoped results,
not a full-repository pass. The interrupted coverage run has no completed
verdict; its replacement focused run completed with bounded-domain reporting
(22.52% overall, not full-suite coverage). A reviewed full-suite coverage
baseline is still absent, and working-tree changed-branch gaps remain recorded
in `remediation-working-tree-coverage.txt`.

Existing full-suite failures were reproduced on unchanged HEAD. The existing
unsafe Mini App route inventory gaps and the dependency exception that expired
on 30 September still block full CI. They were not waived. Supported Python
3.12/PostgreSQL 16 Linux CI execution, clean dependency installation, physical
Telegram behavior, hosted capacity and an isolated backup restore drill remain
release checks (local verification used Python 3.14/PostgreSQL 18 on Windows).

Request-assisted publication does not guarantee progress when all clients are
closed. Legacy invoice attempts with unknown Drive outcomes require reviewed
reconciliation, not blind resend. Windows PDF workers have parent-enforced
timeouts and render budgets, but not Linux `RLIMIT_AS` memory enforcement.
Drain old workers at rollout; no production repairs or Google writes were made.

## Portal usability and cross-workflow audit - 1-October-2026

The audit's identified product defects have local fixes: background publication
is non-blocking and timeout-bounded, payment reviews bind to payment facts,
commissioning chronology is enforced, payment/HB edits have unsaved-leave
protection, payment lists are paginated, and expanded names wrap. Final-review
null handling was also corrected. Historical payment review digests have not
been migrated or restored; affected old open reviews need an explicit new review.

See [the audit report](docs/portal-usability-workflow-audit-2026-10-01.md) for
reproductions, priorities and the repair evidence. The post-repair selection
passed 318 backend tests on isolated SQLite, 84 browser tests and all nine Node
test groups. The 51 local rendered-page samples had no document overflow or
page exceptions; targeted interactions confirmed timeout lease release and
preservation of a second unsaved payment comment. PostgreSQL parity is still
unverified because local test credentials were unavailable. Live Telegram,
Google integration and physical-device checks remain separate release checks;
these results are not a claim that the entire repository suite passed.

## TAT credit assessment first release - 18-September-2026

SPIN and Metropol reports are still produced manually outside this platform;
the platform governs their evidence, questions, responses, and decisions after
upload. The future engine job boundary is deliberately dormant. Gmail polling
uses scheduled command execution rather than push notifications. Enable
`SPIN_HARD_CUTOVER` only after the new migration, personal Gmail OAuth, existing
restricted media Drive folder, staff roles, and live-device smoke test pass.


## JBL Visit document capture - 14-September-2026

Client ID currently uses existing protected Portal media-view scope, not a new
ID-only permission. No role matrix was changed. Local captures survive Case
History inspection but not closing/reloading the app; recapture after a reload.
Camera framing does not certify legibility or that the two images are distinct
document sides; staff must review both before submitting.

Local Windows rendering was verified with WeasyPrint 68.0 and MSYS2 UCRT Pango,
using `WEASYPRINT_DLL_DIRECTORIES=C:\msys64\ucrt64\bin`. The focused test checks
actual one-page Client ID and two-page LAF PDFs, embedded image draw commands,
and deterministic retry output. Live Telegram camera behavior still requires
device validation before release.

## Portal validation scope - 14-September-2026

Case-inspection navigation is locally covered with intercepted browser tests,
including the actual Portal card controllers. Live Android/iOS Telegram device
validation remains an operator release check. A cold/reloaded case link cannot
recover in-memory search or an unfinished local attachment selection; its
visible/Telegram Back uses the allowed source route instead.

The older Django test
`JblPipelineApiTestCase.test_portal_requisition_generate_requires_a_revision_for_each_new_assignment`
targets the retired `/requisition-queue/generate/` path. With a current request
key it returns 426 before revision validation, rather than the old expected
428. It is not evidence for the current preview/finalize path. New inspection
tests verify captured revisions through preview, and a service test verifies
that a changed case cannot be assigned an order. Unrelated old generation
fixtures were not rewritten as part of this navigation change.

The full intercepted browser run passed 49/50 tests. Its unrelated Complaints
report test (`miniapp_flows.spec.js`, date_reported assertion) still expects
`01-09-26`, while the approved current UI renders `01-Sep-2026`. Complaint
formatting was not changed in this Portal-only work.

## Portal reporting v1 scope

The IT-only Portal reporting workspace is deliberately limited to live
`JawabuFarmerMaster` case data, a server-owned field catalogue, named safe
aggregate counts, in-app aggregate visualisations, and local XLSX export. It is not an
arbitrary query builder and currently has no cross-workflow customer joins,
PDF/print output, Drive/Sheets publishing, scheduled delivery, saved data
snapshots, or historical version-diff renderer. TAT, SPIN, Complaint Case and
raw message models are listed through a read-only relationship inventory only;
they must not be joined by name, phone, national ID, or another mutable identity
until a separate ADR, data-owner rule, and release approval exist.

## Free Render publication reliability

The free Render service has no durable worker process. Portal writes therefore
do not wait for Google Sheets or Drive before committing canonical Django
state. A still-open Mini App performs one bounded follow-up publication
attempt; pending work is retained in `IntegrationOperation` or the document
sync fields and resumes on a later relevant Portal visit. This is durable but
not a replacement for a dedicated worker: a Render background worker remains
the recommended future upgrade for guaranteed scheduled retries and alerting.

## Portal import staging is intentionally not a commit workflow

The IT-only Portal Imports screen parses, stores, and reviews FarmUp/SysUp
source files only. It does not expose the existing customer-commit routines.
A future commit workflow needs its own approved maker-checker decision,
explicit row selection, and separate release authorization. Until then, any
Drive archive marked `needs attention` remains retriable from the authorised
Imports screen or support tooling. Archives use their own Imports path beneath
the existing approved Shared Drive root and remain visible only to its
approved members.

## JBL visit evidence after a Telegram/WebView return

Portal restores the current JBL visit's text, date, location and GPS-fallback
reason while the same browser session remains available. Telegram/mobile
browsers do not permit selected `FileList` handles to be retained or restored,
so an officer who temporarily opens the media selector or another screen may
need to reselect the LAF and visit photo before completing the atomic request.
The server validates both categories before it uploads either one; it never
records a forwarded visit without the required evidence.

## Android PDF rendering inside Telegram

Telegram's Android WebView can render a protected image stream in the Portal,
but may display a blank panel for a PDF served through a blob iframe. The
Portal therefore renders the authorized PDF server-side as bounded page images
inside its client-media overlay. It does not use an external Drive link,
browser activity, or Google document viewer. Very large or unusually detailed
PDFs may be rejected for in-app preview and can be retried after a smaller scan
is uploaded through the normal evidence process.

## Pending JBL scheduling backfill

`backfill_jbl_schedule_status` is intentionally dry-run by default. It may be
reviewed locally/staging with `python manage.py backfill_jbl_schedule_status`.
Its `--apply` and `--revert-run` paths change canonical Django status only and
are not authorised for production use until a separate rollout approval.

## Personal notification delivery preferences

`UserMiniAppPreference.alert_mode` remains stored for backward compatibility,
but recipient-level Telegram delivery does not yet apply immediate, digest, or
quiet choices. The Mini Apps intentionally do not render that selector until a
delivery worker enforces the shared mandatory-alert catalogue. Assignment,
approval, security, and overdue-breach alerts are not suppressible.

## Sentry production verification

The Django SDK is pinned, installed, initialized from `SENTRY_DSN`, and tested
with a synthetic DSN. Render's strict production-readiness gate passed on
31-July-2026 after Sentry configuration. The remaining operator verification
is a safe staging synthetic exception: confirm its alert rule fires and that
the event contains no customer/staff payload.

## Business Administrator role cutover

`core.0088_business_admin_role_cutover` was applied in production by the
31-July-2026 recorded migration baseline. It renames effective Portal/TAT/SPIN workflow access from legacy
`ADMIN` to `BUSINESS_ADMIN`, without rewriting historical audit evidence. Run
`python manage.py check_business_admin_cutover --strict` before the production
migration; it blocks unresolved pending legacy access-policy requests or
duplicate effective grant scopes. Capability seed-row overlaps are merged by
preserving the existing allow/deny policy. To undo after a controlled release, run
`python manage.py migrate core 0087_repair_tat_stage_target_snapshot_backfill`;
the reverse migration stops if a legacy-role collision would make rollback
ambiguous.

## Access-control checker bootstrap

`core.0090_accesscontrolcheckerassignment` is accepted for code merge and
local/staging validation only. It records independent checker appointments and
backfills legacy approver-group members without changing Users, Access Grants,
workflow state, financial records, or Mini App access. Before any approved
production rollback, export checker appointment and compliance-audit evidence,
then run `python manage.py migrate core 0089_portalcaseworkspace_portalsavedview`.

## Portal private workspace hold

`core.0091_pause_portal_workspace_to_it` is accepted for code merge and
local/staging validation only. It preserves existing private saved views, pins,
and recents. The Portal Mini App does not render any workspace control for any
role, including IT. The retained endpoint remains IT-gated only for controlled
technical validation; it is not a staff-facing feature. The migration
increments the policy version when it creates policy rows, forcing connected
Mini Apps to refresh permissions on their next metadata poll. It does not
alter customer cases, financial values, Drive/Sheets, or workspace records.

Do not roll back application code to re-open this feature. A future UI
re-enable requires an explicitly approved rollout and the existing capability
review; it must preserve the IT server-side gate. The migration's reverse is
intentionally a no-op so policy and compliance evidence remain retained.

## Portal workspace migration and retention

`core.0089_portalcaseworkspace_portalsavedview` was applied in production by
the 31-July-2026 recorded migration baseline. It adds only private, user-owned saved-view and case-workspace
metadata; it never changes Jawabu cases, workflow state, financial values, or
audit evidence. Django live scope checks hide inaccessible/closed pins
immediately. Until an authorised scheduler is configured, an operator may run
the read-only preview `python manage.py prune_portal_workspace`, then the
explicitly approved `python manage.py prune_portal_workspace --apply` on the
agreed daily cadence to release pins unavailable for 30 days and remove
un-pinned recent metadata older than 90 days. To undo after an approved
release, run:

```powershell
python manage.py migrate core 0088_business_admin_role_cutover
```

The reverse migration drops only the two private workspace tables; it does not
alter case, workflow, financial, or audit tables.

## TAT Settings migration

`core.0085_tattrackercase_stage_target_snapshots_and_more`,
`core.0086_seed_tat_target_snapshots`, and
`core.0087_repair_tat_stage_target_snapshot_backfill` were applied in
production by the 31-July-2026 recorded migration baseline. They add user-owned Mini App
preferences, maker-checker TAT setting proposals, escalation-rule storage, and
target snapshots for active stages. Before any rollback, export approved
configuration requests for audit evidence. To undo the schema locally or after
an approved release, run `python manage.py migrate core 0084_integrationcircuitstate_integrationoperation`.

## Mini App notification preferences

TAT stores an individual user's immediate/daily-digest/quiet preference for
non-critical alerts. Durable TAT action tasks now support shadow evaluation,
existing group alerts, and private delivery with retry and ranked backup
escalation. Production private delivery still requires the approved one-minute
platform scheduler and must pass `check_tat_production_readiness --strict`.
Legacy non-task TAT stage alerts may still be posted to the
configured shared Telegram group, not to individual recipients, so this
preference does not suppress, digest, or reroute those group alerts yet. A
recipient-level notification delivery ledger and scheduled business-day digest
job must be approved and implemented before enabling that behavior. Mandatory
assignment, security, approval, and overdue-breach alerts must remain outside
personal suppression in that future design.

## Bounded integration reliability

`core.0084_integrationcircuitstate_integrationoperation` was applied in
production by the 31-July-2026 recorded migration baseline. It records redacted external
operation/circuit state only; it does not start Celery, Redis, a scheduler, or
any automatic retry worker. Operators can run `probe_integrations` without
side effects for a configuration dry-run. `--execute` makes real read-only
metadata calls and must be an explicitly authorised maintenance action.

The current release routes shared Google Sheets batch writes, Drive uploads,
and Telegram launcher publishing through the durable register. Other legacy
direct outbound calls remain outside it and are listed in `TECH_DEBT.md`; they
must be migrated one bounded workflow at a time with replay tests. Strict Mini
App retry-key enforcement remains disabled until all refreshed cached clients
are verified in real Telegram clients. Do not set
`REQUIRE_MINIAPP_IDEMPOTENCY_KEY=True` during a production release without
that explicit verification and approval.

Last reviewed: 27-August-2026

## Compliance audit evidence

`core.0083_complianceauditchainstate_complianceauditcheckpoint_and_more` is
included in the pending release worktree but is not authorised for production
application. It adds an
append-only cross-workflow ledger, a PostgreSQL application-role immutability
trigger, read-only Admin investigation/export tools, and explicitly generated
daily checkpoint records. PostgreSQL database owners can still alter database
objects, so the ledger is tamper-evident rather than an absolute guarantee.

No automated retention deletion is implemented: every new compliance event is
on legal hold until JBL approves a legally validated retention schedule. No
mailbox delivery, scheduler, or scheduled sampling is enabled. Before enabling
those operations, approve a controlled recipient and mail configuration, test
the PostgreSQL trigger in staging, name an evidence owner, and record a tested
response path for failed delivery. Use `verify_compliance_audit --strict` and
`sample_compliance_audit --strict` only as supervised read-only checks.

## Sheet/Drive publication governance

`core.0082_sheet_register_governance` is committed but is not authorised for
production application. It adds local, publication-only Sheet contracts and
audit evidence; it does not alter Google Sheets/Drive or re-enable inbound
Sheet imports. Before relying on strict audit results, an authorised operator
must review each target tab and create contracts with
`python manage.py seed_sheet_register_contracts` (dry run) followed by the
explicit `--apply` only after the layout is confirmed. Run
`python manage.py audit_sheet_registers --strict` and
`python manage.py audit_drive_permissions --strict` as supervised read-only
checks. No scheduled audit, alert routing, automatic Drive-permission repair,
or periodic Sheets snapshot export is introduced; those need approved
recipients, a durable scheduler, rate-limit handling, and a retention design.

The TAT duplicate repair now verifies and re-publishes each linked survivor,
but it still deletes rows from the chosen live Sheet when `--apply` is used.
Use a copied Sheet first and keep the resulting `LiveSheetRecordChange` audit
evidence. A failed post-delete verification must be investigated manually; do
not rerun a destructive cleanup blindly.

## Portal approval controls and visit evidence

`core.0081_jawabuapprovalcondition_jawabuapprovaldelegation_and_more` is
committed but is not authorised for production application. Approval records,
conditions, temporary delegation, direct case-media links, and retrieval audit
are live only after the approved migration. Legacy farmer decisions and media
remain visible through compatibility reads; they are not retrospectively
asserted to meet the new evidence or authority controls.

The release deliberately does not delete Drive media. Run
`python manage.py audit_jawabu_visit_media --strict` to report unlinked
controlled evidence; it never changes attachments or Drive. Candidate review
and a separately approved retention/deletion policy are still required.
In-app SLA escalation remains an operational signal;
automatic Telegram/SMS/email delivery requires approved recipients, retry
handling, and a scheduled production job.

## Cross-workflow customer data cleanup

The governed customer-resolution rollout currently covers active Jawabu cases
and staged `/sysup` system exports. Complaint Cases, TAT, and SPIN retain
their present records and validations until a separately approved migration
maps their identity fields into the same customer-resolution service. Run
`python manage.py audit_jawabu_data_quality --strict` before a controlled
Jawabu cleanup; the command is read-only and must not be mistaken for a merge
or backfill tool.

## Telegram WebView printing

Telegram's mobile WebView does not provide a dependable browser print stack;
live canvas/browser print previews can be blank. The supported workflow is:
preview the document values in-app, then use **Open Excel** to download/open
the generated workbook in a proper spreadsheet application for printing. Do
not reintroduce `window.print()` as a production document workflow without a
new verified Telegram-client test and ADR.

## Physical document signing

Requisitions and final payment schedules support retention of a physically
signed-and-stamped PDF/JPG/PNG scan. The system records the authorised staff
attestation, source-workbook hash, scan hash, and Drive outcome; it does **not**
verify handwritten signatures, stamps, or legal e-signature validity. The
external e-signature integration remains deliberately on hold. Existing
documents without locally retained source workbook bytes are legacy records and
must be regenerated before a new traceable physical sign-off can be attached.

## Mini App recovery drafts

`core.0072_miniapp_drafts` is applied in the current production migration
baseline. Recovery requires verified Telegram identity and the form's existing
scoped authorization; it cannot promise an offline save. Offline edits remain
in the current open screen and become durable only after the UI shows that the
server saved the draft. Attachments are intentionally excluded.

Required verification before release:

1. A real Telegram mobile test for Portal JBL Visit, SPIN, FCA, FarmUp, and
   System Export draft restore, conflict behaviour, expiration, and attachment
   re-selection.
2. A future form must reuse the shared server draft service and enforce its
   own capability/scope before saving any field state.

### Order Approval browser draft remains

During the draft audit, `core/templates/order_approval/form.html` was found to
retain its own browser-local recovery draft. It was not converted in this
change because its form-token/Telegram authorization path and customer/media
field boundary need a dedicated review before server persistence is introduced.
Do not copy that local-storage pattern into another Mini App. A follow-up must
reuse the `MiniAppDraft` service only after it has a capability/scoped-token
authorization test and confirms attachments stay out of the draft.

## Workflow SLA delivery

The workflow-integrity command records or previews overdue-stage escalations
without sending Telegram messages by default. This is intentional: automatic
notification delivery needs approved recipient routing, rate-limit/backoff
handling, and an explicitly approved Render schedule. Until that operating
change is approved, run the command in dry-run mode and use the resulting
pending escalation records for supervised follow-up.

## Business-calendar and TAT trend operations

Official TAT/SLA time now excludes only dates entered and kept active in Django
Admin under **Business calendar holidays**. The platform deliberately does not
download Kenya public holidays from an external source, so an authorised
operator must confirm the year’s dates before relying on SLA reporting. Run
`python manage.py snapshot_workflow_tat --json` to review the current
projection; `--apply` is an internal, idempotent database write and still
needs an explicitly approved scheduler before it becomes a routine job.
Individual trend rows are emitted only where a workflow has recorded a named
responsible actor. They must be interpreted with the recorded branch, role,
product and paused/deferred-time context; absent attribution stays
role/branch-level rather than being guessed.

## Backup and recovery evidence

The production runbook requires Render daily PostgreSQL backups and quarterly
restore drills, but this repository contains no recorded successful drill or
measured recovery time. Treat the following as operating targets, **not proven
service levels**, until a drill is recorded:

| Store | RPO target | RTO target | Evidence required |
|---|---:|---:|---|
| PostgreSQL | 24 hours | 4 hours | Restore a current backup to staging and record elapsed time. |
| Google Sheets / Drive | 24 hours | 8 hours | Restore a copied/versioned spreadsheet or Drive document to staging and record the result. |

No production data reset, destructive Sheet cleanup, or migration is routine
until the relevant recovery path has been checked.

## Origination separation verification (4 October 2026)

See [the ownership and reference release notes](docs/origination-separation-release.md)
for the independent grant cutover, migration sequence and rollback limits.
Local verification uses synthetic SQLite databases with external network access
blocked. PostgreSQL table/column comments require the wired PostgreSQL CI job
or staging verification; Windows also lacks the native Pango libraries needed
for a full local WeasyPrint integration run.

Six existing Origination tests fail on the unchanged `092ead8` baseline as well
as the separated implementation: three legacy template-add presentation tests,
the former product-bound template upload test, the supporting-document activation
fixture with an empty form contract, and the packet-demo application fixture
without a governed product version. These remain separate from the ownership
change and must be reconciled with the current document catalogue contract.
The repository also retains pre-existing broad gate failures in the Portal
Ruff check, Mini App write inventory, environment parity and dependency exception
expiry. A passing focused check does not establish a passing full release gate.
