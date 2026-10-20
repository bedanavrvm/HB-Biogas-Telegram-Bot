# Platform-independence phase, merge and deployment checklist

Use a change-specific copy at **every phase handoff and every proposed/completed merge or deployment**. Do not report unchecked items as passed. “Not applicable” requires a reason. Branch creation, implementation approval and passing CI do not authorize a merge, production deployment, migration, access-policy change or real external side effect.

Use the existing `docs/production-release-record.md` and `PRODUCTION_RUNBOOK.md` for actual production governance. Keep completed private records, user/cohort identities, credentials and production screenshots outside Git. Link this checklist rather than creating competing release records.

## Current P1c.5 closed native sign-in handoff

ADR 0067 / decision section 11 / plan revision 15 govern this bounded slice.
The user requested continued implementation and easy onboarding/authentication.

- [x] Additions/scope: separate dormant ADS client for session/CSRF, password,
  TOTP/recovery login and logout; autofill, automatic stage resume, username
  retention and inline recovery. No business endpoint or workflow grant.
- [x] Correct stale owned-cookie restart: fresh password/MFA is permitted after
  expiry/revocation; ordinary Admin/other-channel cookies remain protected.
- [x] Dependencies/configuration/schema: no new package/archive/override, secret,
  deployment environment variable, model or migration. Separate build kind and
  opt-in test-only full-schema settings; no reversal command applies.
- [x] Verification: affected staff_auth suite ran 148 tests (139 passed, nine
  PostgreSQL-only skips). After the final mobile markup fix, all five focused
  transport tests passed; production/development each passed 25 native browser
  checks with 10 proof-free captures. TypeScript/full ADS lint, 18 UI/server/ratchet
  tooling tests, changed-Python Ruff, 154 first-party JS syntax checks, architecture
  and source/registry/report/asset bindings pass. Default Django/migration-drift
  checks pass; no migration. CI configured/YAML checked, remote run not executed.
- [x] Preview boundary: root/review return 200 with zero-connect CSP; auth entry
  and native session route return 404. Inspected synthetic captures do not replace
  human design/device/assistive review. The existing environment-example parity
  check still fails on 119 pre-existing declarations; inputs match HEAD.
- [x] Telegram/production: source/identity/role/assets/root dependencies untouched.
  Browser stays globally off/E006 blocking/routes unmounted. No real account,
  provider, Sheets/Drive, merge or deployment action.
- [x] Monitoring: isolated test-loopback traffic only; stop for non-test data,
  external requests, stale hashes or retained proof. Proof stays out of reports.
- [x] Rollback: remove the dormant client/transport/owned-session restart/test/doc
  slice and stop test processes. Preserve identities, credentials, factors,
  sessions, audits and workflow data. No schema/data restore applies.
- [ ] Guided initial-password/enrollment/recovery handoff, actual delivery and
  support. The current setup handoff is not completed onboarding.
- [ ] Human/device/assistive, PostgreSQL/native shared cache/privacy, production
  static/CSP/origin/session integration, backup/support/staging and M0/M1.

## Historical P1c.4 browser composition handoff

The user's "fix the issues ... always refer to the atlassian docs" instruction
is implemented against current official usage/design guidance. Focused forms
keep description/errors/fields/action together; SectionMessage replaces popup
and duplicate feedback; default surfaces replace raised/sunken nesting. The
workspace uses actual Navigation System components and a fixed-wide grid.
Labelled Page/Theme/Response Selects move to `/review.html`; `/` is the staff
presentation. Themes initialize before controls to prevent a dark-input flash.
`browser/AGENTS.md` requires future documentation checks; `browser/DESIGN.md`
maps decisions to official sources. Exact evidence/limits: decision section 10.

- [x] Scope: synthetic standalone browser UI/build/review only. No operational
  data, workflow endpoint, state transition, grant or auth activation.
- [x] Dependencies: exact navigation-system 11.3.1, side-nav-items 2.5.8,
  section-message 10.2.6 and select 23.1.3 added; unused direct inline-message
  removed. Lock-only resolution/archive review precedes scripts-disabled install.
  Current 592 lock entries / 554 archives include 27 newly inspected artifacts.
  171 original installed peers/one existing exception, one renderer and fixed
  selector override pass. Point-in-time npm audit: zero findings. Notices retained;
  emitted logo modules and proprietary images/fonts/brand assets rejected.
- [x] Local checks: production and development/StrictMode each pass 362 checks,
  300 desktop-fit cases and 97 synthetic captures. All eleven normal pages,
  seven forms/four errors, three laptop sizes/two themes, mobile/keyboard/200%
  text and first-field-paint/token checks included. The builds repeat the same
  cases; screenshots and technical passes do not certify design conformance.
- [x] TypeScript, full recommended ADS lint, both builds, 12 focused UI/server
  tests, source ratchet, 153 first-party JS syntax checks and source bindings pass.
  Production: 26 assets / 67 noticed packages / 1,752,528 bytes. Development:
  26 assets / 69 noticed packages / 4,859,188 bytes. Human visual acceptance,
  real devices/assistive/native auth, full CI/Django/PostgreSQL are not claimed.
- [x] Configuration/schema/Telegram: no environment secret, migration, root
  Telegram dependency, Telegram identity/role/UI or backend URL change. Browser
  remains disabled/E006 blocking/routes unmounted. No staff/provider/external
  write, merge or deployment. No migration/reversal command applies.
- [x] Monitoring/rollback: only reviewed loopback asset reads; stop on unexpected
  network, credential collection, stale hashes or repository exposure. Stop the
  server and revert this presentation/dependency/tooling/candidate-doc slice to
  P1c.3; rebuild/restart for that version. Preserve backend identities, sessions,
  credentials, audits and workflow records. No data restore is required.
- [ ] Human design/device/assistive acceptance; never inferred from generated PNGs.
- [ ] Real transport/static/CSRF, proof/recovery/shared cache/privacy/PostgreSQL,
  backup/support, staging, both-channel and M0/M1 acceptance.

## Historical P1c.3 browser viewport layout handoff

The approved viewport plan is implemented using the existing ADS graph: wide
desktop cards put bounded fields beside guidance/status; compact controls open
in an adjacent column; workspace/help/recovery grids use horizontal space; outer
token spacing and footer are compact. Mobile/large text keeps natural scrolling.
Exact source, evidence, diagnostics, limits and rollback: decision section 9.

Executed: each production/development run passes 556 checks with 125 synthetic
captures. This includes 468 viewport-fit cases: all eleven normal pages and four
errors for each of seven forms, at three desktop sizes, both themes and controls
open/closed. Document height/width, visible actions, no clipping/inner scroller
and side-panel position pass. Previous functional/token/mobile/keyboard journeys
remain. TypeScript, complete ADS lint, builds, 11 focused UI/server tooling tests,
153 first-party JavaScript syntax checks and source/UI bindings pass. The two
builds repeat the same cases; do not count them as distinct operational journeys.

Dependencies/configuration/migrations: none; graph/overrides/asset exclusions and
root Telegram packages unchanged. Production: 25 assets, 52 noticed packages,
1,212,635 bytes; development: 3,607,470 bytes. No backend, authority, environment
secret, staff/provider, merge/deploy or Telegram source changes. No new registry
audit was necessary for an unchanged graph; the earlier point-in-time result is
historical. GitHub CI, real devices/assistive technology and native auth were
not accepted here. Browser off/E006/routes and M0/M1 gates remain open.

Monitor reviewed loopback asset reads only. Stop for unexpected external
requests, editable credentials, stale hashes or repository exposure. Rollback
stops the local process and reverts this presentation/test/candidate-doc slice
to P1c.2, then rebuilds/restarts that preview. No migration reversal or backend
record/session/audit restoration applies. Human/device/operational gates remain.

## Historical P1c.2 browser-wide ADS adoption handoff

The user's full browser design adoption request is implemented across all
existing browser pages: ADS layout, typography, navigation, controls and typed
tokens replace custom CSS/native selectors/global overrides. Both recommended
lint sets block drift, including advisory rules; the synthetic read-only field
exception is line-scoped. Two already-reviewed packages become direct uses with
no archive/version/override change. ADR 0066 and decision section 8 govern it.

Executed: each production/development run passes 88 browser checks with 73
synthetic captures; live token comparisons, exact responsive breakpoint,
automatic themes and keyboard review controls included. Type/lint/build/peer/
context/parser/audit, 56 tooling tests and UI/source bindings pass. npm audit:
zero findings. Production build: 25 assets, 52 noticed packages, 1,211,086 bytes.
This evidence is not GitHub CI execution or human/device/native-auth acceptance.

Scope/checklist: decision section 8. No backend, schema/migrations, deployment
configuration, environment secrets, grants or Telegram UI/dependency changes.
Browser remains disabled/E006/routes unmounted; M0/M1 and real transport remain
open. Use Preview controls at http://127.0.0.1:8766/ for review. Monitor reviewed
loopback asset reads only. Rollback stops the server and reverts this browser
design/tooling/candidate-doc slice; retain backend records, sessions and audits.
No migration/reversal command or operational staff/provider action applies.

## Historical P1c.1 actual React/ADS local client handoff

The user instructed “resolve it and proceed”. ADR 0066 and browser/DEPENDENCIES.md
record the exact bounded local installation/build decision, one legacy context
React-peer exception, fixed development selector-parser override, notices and
asset exclusions. The isolated workspace now renders actual ADS components.
After its README build, `python scripts/serve_ads_browser_preview.py` serves
http://127.0.0.1:8766/ on this computer. Source-only port 8765 is historical.

Scope/checklist: BROWSER_REACT_ADS_DECISION.md section 7. Added browser-only
dependencies/build/source/notice inventory, hash-verified loopback server,
focused checks, TSX source ratchet and isolated CI job. No root Telegram
dependency/asset, Django handler/URL/permission, environment secret or schema
change. No migration/reversal command applies. Browser auth remains off/E006
blocking/routes unmounted; no real staff/provider, merge or deployment action.

Executed: 79 production-browser checks/71 synthetic captures; 134 original
installed peer declarations with exactly one documented context exception;
one renderer; context/parser/type/lint/build checks and point-in-time npm audit
zero findings. Output: 25 assets, 52 noticed packages, 1,193,784 uncompressed
bytes including notices/all theme chunks. CI is configured, not claimed executed.
Clean offline scripts-disabled npm ci succeeds; the separate development/StrictMode
build also passes 79 browser checks/71 synthetic captures. These overlap the
production journeys and are not additional distinct business scenarios.
All 56 tooling/governance tests and relevant source/UI/schema-inventory checks
pass. Exact source/capture/registry bindings are verified; limits are in section 7.

Monitor only local reviewed asset reads. Stop for unexpected external requests,
real credential fields, changed build hashes or repository exposure. Human
design/device/assistive review, actual native transport/static/CSP/cache,
proof delivery/recovery, shared native cache/privacy, PostgreSQL and support/M1
remain open. No full-CI/live-provider/production certification is claimed.
Rollback stops the loopback process and reverts only this workspace/tooling/
source-review/docs slice; retain backend staff, credentials, sessions, audit
and workflow records. No database restore or business-data reversal.

## Historical source-only browser access preview handoff

P1c preparation adds first-party synthetic login/setup/MFA/enrollment/recovery,
workspace and help wireframes, a fixed-asset loopback server, source-bound UI
candidate records and focused verification. Open http://127.0.0.1:8765/ after
running `python scripts/serve_browser_access_preview.py`. This is a local review
artifact, not React/ADS installation, operational authentication or a deployment.

Use BROWSER_REACT_ADS_DECISION.md section 6 for the exact change-specific
checklist, evidence, limitations and rollback. Dependencies, environment,
schema/migrations and Telegram/runtime application changes: none. No schema
reversal applies. Stop the local process to contain it; revert only these
review sources/tooling/docs to remove it. No account/session/audit rollback.

Keep browser off, E006 blocking, production routes unmounted and D13/M1 open.
Expected preview traffic is loopback asset reads only; unexpected external
requests, credential input or repository exposure must stop the preview.
Human review, the accepted React/ADS graph/build and operational security/support
remain separate gates. No merge/deploy or real staff/provider action occurred.
Executed: 78 browser checks, 70 synthetic captures, all 50 tooling/governance
tests and relevant source/UI/schema-inventory checks passed. Capture/source
hashes match the candidate registry. No native-auth/real-device/PostgreSQL/live
provider/full-CI/production certification is claimed; previous wider gaps remain.

## Historical P1b.2b.3 closed existing-staff initial setup handoff

Exact-account Superuser preparation now creates only an unverified native
address and encrypted expiring proof for the existing admitted non-Admin account
with an unusable password. Three unmounted CSRF handlers perform session-bound
native verification and first-password save with atomic receipts; setup grants
no login/MFA/workflow authority and has no proof dispatch/export. Review actual
shared Django session-hash consequences separately from browser-only revocation.

Migration `staff_auth.0003_staffbrowsersetupgrant` is additive. Normal rollback
retains accepted native credentials and audit. Exact destructive pre-use reversal:
`python manage.py migrate staff_auth 0002_stafftotpreplaystate`. Never reverse or
clear live setup grants while a worker can consume them. Preview-first retention
cleanup preserves native credentials and audit. No real preparation, password,
mail, merge or deployment action is performed here.

Use STAFF_BROWSER_INITIAL_SETUP.md sections 6–7 for current verification, limits
and the change-specific merge/deploy/monitoring checklist. Browser remains off,
E006 blocking and production routes unmounted; actual deployed state, delivery,
support, shared cache/privacy, PostgreSQL, frontend/D13 and M1 remain open.

## Historical P1b.2b.2 shared browser TOTP handoff

The closed browser MFA adapter now reserves one native-validated TOTP use in a
shared database table before authentication is saved. Native-normalized variants
share one factor-seed HMAC key; live claims are not evicted. Native recovery codes
and the global cache remain unchanged. Migration
`staff_auth.0002_stafftotpreplaystate` is additive; normal rollback preserves it.
Exact destructive pre-use reversal: `python manage.py migrate staff_auth 0001_initial`.
Never reverse or clear claims while browser workers can authenticate.

`purge_staff_totp_replays` previews a bounded expired-only batch; no operational
cleanup or scheduler is run. Use STAFF_BROWSER_REPLAY_GUARD.md sections 4–5 for
actual verification, limits and change-specific merge/deploy/monitoring checks.
Browser remains off/unmounted, E006 blocking, production state unknown and
provisioning/recovery/native shared rate-cache/frontend/M1 acceptance open.
Restoring the existing pinned local allauth package changes no manifest.

## Historical P1b.2b.1 closed-enrollment handoff

New backend TOTP enrollment and one-time recovery-code handoff use the existing
pinned allauth forms/flows. Begin rechecks the password; factor activation and
code-view marking roll back if audit fails. Setup never issues MFA assurance;
explicit logout and a new password/MFA login are required. No staff provisioning,
factor replacement, new schema/dependency/configuration or Telegram UI change.
Production remains unknown, browser globally off and production URLs unmounted.

Use `codebase-analysis-docs/assets/STAFF_BROWSER_ENROLLMENT.md` sections 5–6 for
actual evidence and the change-specific merge/deploy/monitoring/rollback list.
Review same-key retries versus nonrepeatable recovery disclosure, 400/401/403/
409/429/503 results, actual ledger/factor consistency, interrupted enrollment and
existing Telegram/Admin journeys. Never log/capture codes or enrollment URIs.
No new enrollment traffic is expected on production: unexpected exposure is an
incident, not a successful rollout. Keep E006 blocking. Native shared replay
cache, provisioning/support/mail, React/ADS acceptance and M1 remain open. No
merge or deployment is performed or authorized by this local handoff.

## 1. Identify the change

- [ ] Phase/app/milestone and primary business driver.
- [ ] Actual branch, exact proposed/deployed commit, target branch/environment and previous known-good release.
- [ ] Plain-language additions/changes and **what is deliberately unchanged**.
- [ ] Files/services/UI assets affected; identify every shared Telegram consumer.
- [ ] Evidence level: source inspected, checks/tests executed, staging verified, production verified or unknown.
- [ ] D1/identity and other relevant gates resolved; named release, workflow and backup/support owners.
- [ ] Explicit merge/deployment authority recorded; inspect automatic deployment hooks before merging.

## 2. Before merge

- [ ] Diff is bounded; pre-existing/unrelated edits and customer data/secrets are not included accidentally.
- [ ] Required structural/dependency/access decisions reviewed; no automatic cross-workflow authority.
- [ ] Changed browser paths remain separate from CSRF-exempt Telegram endpoints; no production `access=None` fallback.
- [ ] Actual owning workflow scope is preserved. In Complaints, do not replace the current group-shared read policy with blanket branch isolation.
- [ ] Focused tests, affected Telegram/browser regressions, static/governance checks and applicable full-CI results recorded; include failures/skips/not-run reasons.
- [ ] Shared assets tested in both channels, including stale cached Telegram clients where affected.
- [ ] UI source ratchet/review respected; no candidate theme migration or baseline update without approval.
- [ ] Configuration variables/defaults, dependency changes, schema migrations and catalogue metadata explicitly listed—or state **none**.
- [ ] Unresolved issues have owners; no focused green run is presented as a green full suite.

## 3. Before deployment or activation

- [ ] Confirm actual deployed state and migration plan, not just local HEAD.
- [ ] Existing production-release/readiness process followed; backup/restore reference and exact migration compatibility/reversal/forward-fix recorded if applicable.
- [ ] New browser channel/cohort/surface/write admission stays closed during deployment unless that exact activation is approved.
- [ ] Current Telegram auth, bot/webhook, launcher, notification and staff-binding defaults remain as reviewed.
- [ ] IdP/cookie/CSRF/session-assurance/revocation settings validated if changed; never list secret values.
- [ ] Current operator can contain the affected surface; backup can execute the procedure; actual rehearsal observations recorded.
- [ ] Worker overlap, long uploads, queues/leases and static-asset compatibility reviewed if affected.
- [ ] Runtime deployment and user/cohort activation treated as separate decisions.

## 4. Things to look out for after merge/deployment

- [ ] Existing authorized Telegram launch, list/detail and relevant write still work; no surprise company-login requirement.
- [ ] Wrong-group/workflow/role and revoked/inactive access is rejected according to existing policy.
- [ ] Browser session/CSRF failures do not cause a silent credential fallback or login loop.
- [ ] Correct actor, revision and audit appear for real approved changes; no duplicate comments, approvals, deposits or publication reservations.
- [ ] An uncertain/timed-out save is reconciled before retrying through another channel.
- [ ] Sheet/Drive publication, pending work and task routing show the expected distinction from canonical save success.
- [ ] No unintended Telegram/email/SMS/Daraja call, double-send, changed escalation or evidence disclosure.
- [ ] Shared UI, downloads, dirty-form protection and old cached WebViews behave as reviewed.
- [ ] Staff-reported errors/delays, safe logs and actual scripted journeys reviewed by a named human; no fabricated percentage thresholds for tiny cohorts.
- [ ] Support owner checks the next agreed business review point and records go/hold/contain/rollback.

## 5. Rollback and closure

- [ ] Browser-only fault: close only the affected browser surface/new admissions where possible; preserve Telegram access and committed state.
- [ ] Shared-code fault: use compatible known-good application or reviewed forward fix; a browser flag alone may not repair Telegram.
- [ ] Preserve audit, signatures, finance claims and valid pending work; no automatic business reversal or duplicate external dispatch.
- [ ] Database restore is disaster recovery with explicit authority, not routine feature rollback.
- [ ] Record actual rollback/containment actions and results, unresolved gates and next owner.

## P0 discovery-only handoff

Expected additions: source endpoint/side-effect manifest, prerequisite register, local check results and this reporting template. Runtime/API/UI/configuration/dependency/schema additions: **none**. Browser access: **not implemented**. Required next input: IdP/MFA, primary driver, first Complaint audience and deployed baseline. No migration, webhook change, staff activation, provider call or deployment is required to review these files.

## P1a dormant foundation handoff

The later user decisions and actual P1a additions supersede the P0-only status,
not its historical evidence. Use the completed scope, verification, activation
blockers and specific monitoring/rollback checklist in
`codebase-analysis-docs/assets/STAFF_BROWSER_MFA_FOUNDATION.md` for this phase.
Dependency and 12 vendor migrations are deployment considerations; browser
admission stays off. No merge/deployment has been performed or authorized.

## P1b.1 backend lifecycle handoff

Current slice: one admission model/migration, audited opt-in/suspend/revoke/reset
service, preview-first command and assurance generation checks; no UI or business
API. Use `codebase-analysis-docs/assets/STAFF_BROWSER_LIFECYCLE.md` for this phase's
actual additions, evidence, limits, rollback and monitoring checklist. Admission
remains globally off. P1a was committed separately while this phase ran; no
commit/merge/deployment was performed by this phase and production remains unknown.

## P1b.2a JSON/storage and React decision handoff

Current slice: constrained JSON auth handlers, durable success audit and protected
pending-TOTP session storage, using the existing pinned allauth distribution.
No production auth/business routes, new migration/env variable or dependency;
browser stays globally off and activation checks stay blocking. See
`codebase-analysis-docs/assets/STAFF_BROWSER_JSON_AUTH.md` for exact scope,
verification, unresolved gates and the change-specific monitoring checklist.

React + ADS is selected for the new browser client, not a Telegram rewrite.
The user requires exact package/transitive/asset licence review first; no frontend
packages/assets/build are installed. Before any future frontend merge/deploy,
add the accepted licence/NOTICE record, pinned browser build, component/token/lint
evidence, accessible login/error behavior and isolated hashed-asset rollback.
See `codebase-analysis-docs/assets/BROWSER_REACT_ADS_DECISION.md`. No deploy or
merge is authorized by this handoff.

## D13a exact frontend dependency review handoff

Evidence/tooling only: a proposed exact login/shell manifest, temporary
scripts-disabled lock resolution, integrity-checked archive metadata/licence/
asset inventory and offline verification/tests. These do not install or approve
React/ADS, change application configuration or mount browser routes. Current
scope, executed results, unresolved findings and the phase-specific checklist
are in `codebase-analysis-docs/assets/BROWSER_REACT_ADS_DECISION.md` section 5.

On merge review, confirm the root dependency/build files, Django settings/URLs,
migrations, permissions and Telegram assets are unchanged; inspect only the
analysis review artifacts/tool/tests, explicit `.gitignore` JSON exceptions and
associated documentation. No deployment, schema reversal or production monitoring
change is required. Keep installation held until the exact candidate/graph,
licence/asset/notice obligations and build scope are accepted. A checker pass is
evidence consistency, never licence approval or browser operational readiness.
