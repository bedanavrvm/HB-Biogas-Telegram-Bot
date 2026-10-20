# Changelog

## 20 October 2026 - Guided closed browser onboarding (P1c.6)

- Connected prepared invitation, native first-password, QR/manual-key enrollment
  and one-time recovery handoff in the dormant ADS client. Autofill, bound-session
  resume and no duplicate password prompt keep the flow short.
- Added read-only setup/enrollment progress and local native QR generation using
  the existing allauth MFA dependency. Transient proof is masked in captures;
  lost recovery-code disclosure is never automatically repeated.
- Production stays off/unmounted; no package, schema, migration, grant, Telegram,
  real delivery or deployment change. ADR 0068, decision section 12 and the
  release checklist record verification and remaining M0/M1 gates.

## 20 October 2026 - Closed native browser sign-in integration (P1c.5)

- Added a separately built dormant React/ADS client for real same-origin Django
  session/CSRF, password, TOTP/recovery login and logout. Automatic stage resume,
  autofill, username retention and inline recovery keep routine sign-in short.
  Uncertain requests reconcile the session without replaying credentials.
- Fixed an expired/revoked browser-owned cookie blocking a fresh sign-in;
  unrelated Admin/other-channel sessions remain protected. Added native browser
  integration and regression checks under ADR 0067; exact executed results and
  open gates are recorded in decision section 11 and the release checklist.
- Kept recovery/cancel actions stable during field validation and removed an
  empty mobile navigation menu. Final native browser checks pass in both build
  modes; PostgreSQL-only and operational acceptance remain explicitly open.
- The accepted synthetic preview stays separate and data-free. No operational
  route, browser activation, workflow authority, dependency, schema or deployment
  change. Guided onboarding/setup, real delivery/support and M0/M1 remain open.

## 20 October 2026 - Documentation-led browser composition correction (P1c.4)

- Reworked focused access tasks and the workspace against official ADS guidance.
  Descriptions and persistent section errors stay with the form; repeated field
  warnings/popup feedback and raised-page/sunken nesting are removed. Workspace
  navigation uses actual Navigation System and current side-nav-items.
- Initialized theme tokens before controls to eliminate the dark-mode input
  background flash; first-frame checks and transition-stable captures cover it.
- Moved synthetic Page/Theme/Response controls to a separate review entry using
  labelled ADS selects. Added browser-specific instructions/reference mapping
  requiring consultation of current official docs before UI work. Earlier
  component/lint/viewport success is not evidence of full design conformance.
- Reviewed four exact ADS additions and changed archives before installation;
  strict peers, the existing exception, notices and proprietary-asset exclusion
  remain. Audit: zero findings. Exact evidence and results: decision section 10,
  ADR 0066 and plan revision 14. No backend, grant, schema or production change.

## 20 October 2026 - Browser viewport layout (P1c.3)

- Replaced narrow stacked access cards with wide ADS layouts: bounded fields
  beside guidance/status, compact review controls in a desktop side column,
  four-column workspace tools and multi-column help/recovery content. Reduced
  outer spacing and used a compact footer without shrinking typography.
- Added explicit viewport-fit checks for every page and form error in both
  themes, controls open/closed, at 1280x720, 1366x768 and 1440x900. Checks reject
  vertical overflow, offscreen actions, clipped content and inner-scroll fixes.
  Mobile and enlarged text continue to scroll naturally.
- Scope, final evidence and rollback are in decision section 9 and plan
  revision 13. No dependency/backend/schema/grant/Telegram/deployment change;
  the browser remains a disconnected local demo with operational gates open.

## 20 October 2026 - Browser-wide ADS design adoption (P1c.2)

- Replaced custom browser CSS, the split introduction and native review
  selectors with ADS Box/Grid/Inline/Stack layouts, Anchor/LinkButton navigation,
  Heading/Text typography and button groups. Every existing access page shares
  the ADS shell, typed semantic tokens and supported responsive breakpoint.
- Enforced both ADS lint plugins' complete recommended rule sets as errors,
  removing layout/global-style exemptions. A line-scoped read-only exception
  protects synthetic demo credentials. ADS typography tokens remain unchanged
  with system-font fallbacks; no proprietary font/image/brand asset is added.
- Promoted two already-inspected transitive packages to exact direct use without
  changing archive versions or peer/security exceptions. Builds now bind exact
  source hashes; runtime checks compare actual styles to loaded ADS tokens and
  exercise the responsive grid, keyboard controls and automatic theme changes.
- Scope and final verification are recorded in decision section 8, ADR 0066 and
  plan revision 12. Browser auth remains disabled and disconnected; no backend,
  workflow grant, Telegram UI, schema, environment secret or deployment changes.

## 20 October 2026 - Actual React / Atlassian access client (P1c.1)

- Installed the isolated `browser/` React 18/ADS workspace and supported
  Parcel/Compiled build under the user's “resolve it and proceed” instruction.
  Exact review binds 555 lock entries/528 archives. A scoped legacy context peer
  exception is explicit; the fixed selector parser and supported ESLint resolve
  the initial toolchain audit finding. Root Telegram dependencies are unchanged.
- Added real ADS provider, controls/forms, typography and themes to the local
  access demo, readable third-party notices, excluded-asset/module checks and
  a hashed loopback-only server at port 8766. The custom wireframe on 8765 is
  historical. Demo values remain read-only; no real auth/business API is connected.
- Added TSX source-review coverage and dedicated CI checks. Local production
  build, types/lint/context/parser/peer checks and 79 browser checks/71 synthetic
  screenshots pass. Point-in-time npm audit reports zero vulnerabilities.
- No Django auth/permission/schema/config-secret/Telegram source change, real
  staff/provider action, merge or deployment. Browser off/E006/routes and M1
  gates remain. ADR 0066, plan revision 11 and decision section 7 record exact
  scope, diagnostics, unverified release work and rollback.

## 20 October 2026 - Local synthetic browser access preview

- Added review-only sign-in, first-password/setup, MFA/enrollment/recovery,
  workspace and help wireframes, with fixed demo values and simulated failures.
  A loopback server serves only their three first-party assets, independently of
  Django. No account changes, API calls, cookies, persistent storage or vendor
  code/assets. Root dependencies and Telegram sources remain unchanged.
- Added candidate source hashes/component inventory, browser and server checks,
  and plan revision 10. The React/ADS dependency/peer/licence gate remains open;
  this preview is not the working React client or an M1/production release.
- Local access, evidence and rollback:
  `codebase-analysis-docs/assets/BROWSER_REACT_ADS_DECISION.md` section 6.
- Verification: 78 browser checks, 70 synthetic captures, all 50 tooling tests
  and relevant lint/UI/source/governance checks passed. Human design, React/ADS,
  native authentication, real devices, staging and production remain unverified.

## 20 October 2026 - Closed existing-staff initial setup (P1b.2b.3)

- Added active-Superuser, preview/snapshot/revision/request-key-controlled
  preparation of the exact existing admitted non-Admin account's canonical
  unverified address. No signup, identity matching, grant changes or usable
  credential reset. Encrypted native proof is bound to one expiring preparation;
  operator output never exports proof or credentials, and no mail is sent.
- Added three unmounted CSRF handlers for anonymous setup bootstrap, native
  mailbox verification and native first-password validation/save. Audit failure
  rolls back credentials; session-bound retries cannot switch accounts or grant
  business/MFA access. Fresh normal login and MFA enrollment still follow.
- Added `staff_auth.0003_staffbrowsersetupgrant`, bounded security-state metadata
  and preview-first expired-only cleanup. Accepted native credentials and audit
  survive normal rollback. Initial password setting changes that user's Django
  session hash; Telegram signed-launch identity/grants are preserved.
- Browser remains off, E006 blocking and production routes unmounted. No new
  dependency/env variable/frontend/global cache, real staff/provider action,
  merge or deployment. Real mail/support, shared cache/privacy, frontend and M1
  acceptance remain open. Verification and release checklist:
  `codebase-analysis-docs/assets/STAFF_BROWSER_INITIAL_SETUP.md`, ADR 0065.
- Final isolated auth/Telegram/user-lifecycle run: 187 tests, 178 passed and nine
  PostgreSQL-only skips. Two overlapping configured-password-hasher journeys,
  all 44 governance/tool tests, narrow Ruff, catalogue/static checks and isolated
  migration reversal passed. Known wider CI and operational gates remain.

## 20 October 2026 - Shared browser TOTP one-use guard (P1b.2b.2)

- Restored the already-pinned allauth MFA dependency in the local environment;
  no manifest pin or frontend dependency changed.
- Added a shared database reservation after native code validation in the closed
  browser MFA input, including native punctuation normalization, safe storage
  failure and unchanged authenticated lost-response retries. Native recovery
  codes retain their existing one-use path.
- Added the bounded `StaffTOTPReplayState` security table and additive migration
  `staff_auth.0002_stafftotpreplaystate`, catalogue metadata and preview-first,
  bounded expiry-only cleanup. Live claims are never evicted by this maintenance.
- Browser stays disabled and production routes unmounted. Global cache,
  Telegram assets/authentication, grants and business workflows are unchanged.
  Provisioning/recovery/support, shared native rate-limit caching, frontend
  acceptance and M1 remain open. No production mutation or deployment.
- Evidence, remaining limits and change-specific migration/rollback checklist:
  `codebase-analysis-docs/assets/STAFF_BROWSER_REPLAY_GUARD.md` and ADR 0064.
- Final isolated auth/Telegram/user-lifecycle run: 156 tests, 150 passed and six
  PostgreSQL-only skips. All 44 governance/tool tests, catalogue/static checks
  and additive/reversal rehearsal passed; known wider CI findings remain.

## 19 October 2026 - Closed native TOTP enrollment backend (P1b.2b.1)

- Added three unmounted, cookie/CSRF JSON handlers for password-rechecked native
  TOTP setup, activation and one-time recovery-code handoff. Seed storage remains
  dedicated-key encrypted; native allauth owns code algorithms and credentials.
- Added admission/session/receipt-bound nonprivileged progress, owner locking,
  retry-safe activation and fail-closed transactional audit. Recovery disclosure
  cannot be replayed or silently regenerated. Setup never issues MFA assurance;
  explicit logout and a new password/MFA login follow.
- Updated ADR 0063, plan revision 7, glossary and per-phase merge/deploy checklist.
  No dependency, migration, environment name, staff provisioning, grant, Telegram
  UI or production URL change. Browser remains off; E006 stays blocking. No
  merge/deploy/provider write or real enrollment performed. Scope, executed
  verification, remaining gates and monitoring/rollback checklist:
  `codebase-analysis-docs/assets/STAFF_BROWSER_ENROLLMENT.md`.
- Final verification: 136 focused auth/Telegram/user-lifecycle tests passed, four
  PostgreSQL-only tests skipped; all 44 governance/tool tests, Node checks and
  relevant static/schema/catalogue checks passed. Existing 119 environment-
  template and 17 artifact-allowlist findings remain; full CI/production unproven.

## 19 October 2026 - Exact browser dependency evidence (D13a, review only)

- Added an exact login/shell review candidate, review-only lock/archive inventory
  tooling and offline evidence/safety tests. Public package archives are verified
  and inspected without extraction, installation or lifecycle execution; metadata
  and hashes stay under `codebase-analysis-docs/assets/`.
- Found a material original-peer conflict: the analytics context dependency
  declares React 16-only support while other proposed dependencies need React 18.
  The override-assisted graph is retained for forensic licence inspection only,
  not approved for installation. React 19 also conflicts with browser-apis 1.2.0.
- Updated the plan/ADR and phase-specific review/merge checklist. No runtime,
  permissions, migrations, configuration, root dependency/build files or Telegram
  UI changed. Browser remains closed; no commit/merge/deployment performed.
  Current evidence, limits and remaining decisions:
  `codebase-analysis-docs/assets/BROWSER_REACT_ADS_DECISION.md`, section 5.
- Final evidence: 529 unique archives / 546 locked entries inspected with no
  remaining errors; 44 governance/tool tests, offline snapshot binding and
  relevant fast checks passed. Unresolved peer/licence/asset/build decisions are
  preserved; these results do not claim legal clearance or frontend readiness.

## 19 October 2026 - Dormant JSON auth boundary and React browser direction (P1b.2a)

- Updated the phased plan for a separate React/Atlassian Design System browser
  frontend, preserving Telegram UI and Complaints → TAT → Origination → Portal.
  User-selected exact package/transitive/asset licence review gates installation;
  no React/ADS/build dependency or asset is installed. Initial five direct
  Atlaskit artifact licences/integrities were inspected, not the complete tree.
- Added constrained session/password/MFA/logout JSON handlers over the pinned
  allauth browser implementation, with CSRF, explicit mixed-credential rejection,
  current admission and durable login audit. Password-only sessions never qualify
  for business access. All production auth/business URLs remain unmounted.
- Added dedicated-key, expiring, user/admission-bound pending-TOTP session
  protection without changing Django's global session backend. Enrollment,
  provisioning, recovery, shared replay cache and support remain separate gates.
- Enabled the model-free headless app from the existing pinned allauth package;
  no new dependency, migration or environment variable. Browser admission stays
  off. Scope, verification, remaining limits and monitoring/rollback checklist:
  `codebase-analysis-docs/assets/STAFF_BROWSER_JSON_AUTH.md`. No merge/deployment
  or production staff/customer/provider change performed.
- Verification: 113 focused tests passed, two PostgreSQL-only concurrency tests
  skipped on SQLite; 28 governance-script tests, Node tests and relevant fast
  checks passed. Existing environment/artifact audit failures remain visible;
  full CI, real PostgreSQL/devices and staging acceptance are not claimed.

## 19 October 2026 - Browser admission and revocation controls (P1b.1)

- Added explicit existing-staff browser opt-in, audited suspension, browser-only
  session revocation and support-reference-bound MFA reset. The preview-first
  operator command requires a currently active Superuser, reviewed revision,
  stable request key and reason for writes; audit failure rolls back the action.
- Added `staff_auth.0001_initial` for one commented, catalogue-governed admission
  table, without data backfill. Browser assurance now binds its UUID/revision
  and rejects authentication started before the latest lifecycle boundary.
- Preserved shared sessions, Telegram bindings, passwords and workflow grants.
  Classified allauth email/factor credential rows in the existing governed user
  deletion registry; admission/original identity and compliance evidence survive.
  Also classified two already-expiring viewer-recognition caches; immutable
  settled recognition snapshots and workflow evidence are unchanged.
- Refreshed the generated database catalogue, including prior stale usage
  references. No dependency/configuration/UI/URL addition or production action.
  Browser admission remains off; P1b.2 operational login/enrollment/recovery and
  M1 acceptance remain open. Verification and the change-specific checklist:
  `codebase-analysis-docs/assets/STAFF_BROWSER_LIFECYCLE.md`.
- Final focused run: 95 tests passed, two PostgreSQL-only tests skipped; ten
  crypto/configuration checks and 28 governance-script tests passed. Full CI,
  PostgreSQL and live-device acceptance are not claimed; known wider failures
  remain documented.

## 19 October 2026 - Dormant staff browser MFA foundation (P1a)

- Added user-selected Django/allauth TOTP and recovery-code integration against
  existing staff accounts, dedicated-key secret encryption, server-owned MFA
  assurance and fail-closed activation checks. No production login, enrollment,
  recovery or browser business URLs are mounted; the flag must remain off.
- Preserved Telegram signed-launch authentication, existing Admin login,
  independent workflow grants and business services. Vendor credential/email
  Admin editors are hidden, not adopted as recovery tools.
- Pinned `django-allauth[mfa]==65.20.0` in both manifests; its 12 additive vendor
  migrations require the normal authorized release review even while dormant.
  No production migration/deployment, account provisioning or provider write.
- Added synthetic vendor password/MFA/CSRF and assurance tests; corrected the
  existing Telegram test's positional diagnostic-ID assumption without changing
  production IDs. Verification, limitations, rollback and the required
  change-specific checklist are in
  `codebase-analysis-docs/assets/STAFF_BROWSER_MFA_FOUNDATION.md`.
- Final focused run: 53 authentication/identity tests and 28 governance script
  tests passed; wider audit/catalogue/environment checks have documented gaps.
- Browser MFA first is approved; forcing password/MFA inside Telegram is not.
  Operational provisioning/recovery/support and M1 acceptance remain unfinished.

## 19 October 2026 - HB Deposits and JBL first-visit eligibility

- Added HB Actions → Deposits for scoped HB staff to record cumulative HB totals
  with revision/request-key protection, actor/time Activity and explained
  downward corrections. Operations Administrators view only. The pre-visit
  editor locks after the current cycle's first JBL visit.
- Blank/zero/below-KES-5,000 cases stay visible but greyed out in the JBL queue.
  Services enforce the same threshold before evidence processing and the final
  visit commit. Already-recorded visits and downstream finance remain intact.
- Under-funded office leads save intake only, without visit evidence or a false
  visit-success result. Reviewed FarmUp accepts valid missing-deposit intakes;
  later imports cannot overwrite an HB-owned total and retain discrepancies in
  Activity. The generic correction screen cannot bypass the HB editor.
- Added capability-default migration `0208_hb_deposit_capabilities`, policy
  refresh and a separately authorized, dry-run-first legacy review repair with
  audit-preserving reversal. No new models, Sheet columns, provider calls or
  production deployment. Operational contract and UI candidate evidence:
  `codebase-analysis-docs/assets/HB_DEPOSITS.md`; verification: `KNOWN_GAPS.md`.
- Final focused validation: 233 backend tests passed, two PostgreSQL-only tests
  skipped, and all 268 Portal browser checks passed. The wider legacy backend
  suite is not fully green; PostgreSQL, real-device and deployment acceptance
  remain explicit release gates.

## 19 October 2026 - Portal lead responses and document chronology

- Fixed JBL office-lead completion returning no HTTP response after visit
  processing. Expected failures now return field feedback; untouched failed
  intake pairs are removed through a guarded service, while evidence and
  progressed/retried cases survive.
- New order previews/workbooks use oldest intake first. Payment previews and
  workbooks use Eco-conserve first, oldest first within each partner. Intake
  age uses HBG visit/sign date, falling back to Nairobi creation date with
  stable ties. Existing retained/signed document bytes are not regenerated.
- Corrected obsolete Portal test fixtures/expectations for the current shared
  confirmation, download-link, recovery handoff, compact preparation UI,
  canonical product label, historical case scope and explicit pagination dates.
  No operational HTML/CSS/JavaScript or visual baselines changed.
- Moved order-workspace event persistence into its transaction-guarded service
  and documented 34 existing route contracts in the write inventory. This
  changes neither capability policy nor workflow grants. Launcher discovery
  remains an explicitly inventoried read-only authentication boundary.
- No schema, environment, financial-value or numbering changes. No production
  deployment, migration or provider writes were performed. Verification and
  remaining operational gates are in `KNOWN_GAPS.md` and
  `codebase-analysis-docs/CODEBASE_KNOWLEDGE.md`.

## 19 October 2026 - Optional Origination phone registration IT pilot

- Added a disabled-by-default, scoped-IT-only advisory check beside saved
  Applicant primary/alternate phones, including read-only applications. One
  operator confirmation is required; this does not assert customer consent.
- Exact conclusive phone/National-ID results can be reused across Origination
  applications for thirty days with application-local audited receipts. Atomic
  Nairobi-day dispatch accounting caps the pilot at fifty calls; there are no
  automatic paid retries or application/signing-state changes.
- Added core migration 0207 and Origination 0010/0011, governed independent
  evidence tables, safe Daraja adapter, capability seeding/policy refresh and
  synthetic tests. No production migration, provider call or deployment ran.
- Deployment and review gates: `codebase-analysis-docs/assets/PHONE_ID_CHECKS.md`.
  Operational rollback disables the feature. Destructive reversal, after
  authorized backup/export and checking later migrations: `python manage.py
  migrate origination 0009_signer_sms_provider`, then `python manage.py migrate
  core 0206_advanta_integration`. Never delete counters to release allowance.
- PostgreSQL concurrency, live-provider/commercial onboarding and human/native
  UI review remain activation gates; see the verification record for results.

## 16 October 2026 - Accurate Origination SMS schema readiness

- Delivery readiness now checks the migration register before reading the new
  SMS schema. Expected pending SMS migrations are deferred during pre-deploy,
  then rechecked after migration before a release can be recorded as completed.
- Missing migrations are named explicitly. Database connectivity, permissions
  or query failures have a separate safe diagnostic instead of incorrectly
  claiming migrations are missing. No database exception text or secrets leak.
- Configuration errors, provider retention checks and stale-runner warnings
  remain intact. No new migration, signing-policy change or SMS send is added.

## 16 October 2026 - Origination draft document management

- Replaced Change Main LAF with one Manage documents chooser, including when
  only one Main LAF is available. Officers can add/remove supporting documents
  and capture eligible newly published types without upgrading captured versions.
- Supporting changes retain the application, saved answers and evidence. Visible
  fields/sections, required evidence, signing obligations and preview validity
  follow the selected documents. Supporting forms honour their placed fields,
  configured section headings and input types; section navigation saves edits.
- A confirmed Main LAF change cancels the source and creates a blank application.
  Answers, uploads and custom signing assignments do not transfer. Accepted
  historical retries still return their original replacement without erasing it.
- Reused the existing compact sheet and controls, with phone light/dark and
  failure/retry evidence. No design-token migration, schema migration, role
  changes, provider calls or production deployment are included.

## 16 October 2026 - Optional Advanta Origination SMS

- Added environment-selected Advanta transactional SMS alongside Africa's
  Talking, which remains the default. Existing signing links retain their SMS
  provider; OTP rules, document bytes and independent Mini App roles remain intact.
- Bound all SMS submissions, including withdrawal notices, to one automatic
  attempt. Unknown sends are not blindly retried or routed to another provider.
- Added authenticated, bounded Advanta delivery lookups to the Origination
  runner, provider-aware recovery/readiness and redacted delivery evidence.
- Signing feedback distinguishes an accepted send from confirmed handset
  delivery and keeps saved signatures/code entry usable after uncertain sends.
- Disabled Sentry frame-local capture so OTP text and API credentials cannot be
  collected from transport stack variables; existing error grouping is retained.
- Deployment needs the checked-in SMS migrations, provider credentials and a
  once-per-minute delivery runner. No live SMS or production changes were made.

## 16 October 2026 - Source-bound Mini App Design Lab

- Added a disabled-by-default, active-Superuser-only `/ui-lab/` workspace for
  Portal, TAT Tracker, Complaints and Origination. It includes a 31-pattern
  catalogue, source-backed specimens, three candidate densities, Telegram/JBL
  theme previews, comparison controls and explicit Telegram device checks.
- Added immutable source/evidence revisions, append-only design decisions,
  review filters, private synthetic screenshot uploads and reviewed-standard
  exports. Changes requested are not approval; source drift invalidates current
  adoption without deleting earlier decisions. Retries retain one meaning.
- Added reproducible source/capture tools, CI evidence artifacts, the UI source
  ratchet, scoped release/token checks and agent reuse guidance. Business I/O,
  page redirects and native controls are isolated inside synthetic specimens.
- Operational Mini App appearance, permissions and workflow rules are unchanged.
  No designs are pre-approved. **Phase 6 migration is not started or authorised.**
- Normal deployment requires the checked-in `ui_review` migration and
  `UI_DESIGN_LAB_ENABLED=True`. The lab then appears in Superuser Admin/JBL Apps
  navigation; no new bot is required. This work was not deployed.
- Verification: 21 focused backend, 15 browser and five UI-guard tests passed.
  Light/dark narrow-phone screenshots were inspected. Broader checks expose
  unchanged existing index, route-inventory, settings-parity and API-boundary
  issues. Specialised fixtures, font/native-device checks and human approvals
  remain explicit gaps; see `docs/ui-standard/implementation-status.md`.

## 15 October 2026 - Signed payment upload confirmation

- Payment Preparation now asks for a simple confirmation that the selected copy
  is complete, signed, stamped, readable and matches the current payment document.
  The upload includes the attestation already required by the server; its omission
  was causing valid signed-copy submissions to return HTTP 400.
- Cancel keeps the selected file. Repeated clicks cannot start a second upload,
  and a changed payment must be reopened before confirmation can proceed. A saved
  scan awaiting Drive retry is clearly distinguished from payment completion and
  directs staff to the existing Document History retry action.
- Current-review, document-version, access and file checks remain unchanged.
  No payment facts, saved documents or production data were modified.
- Verification: 64 affected backend tests passed on isolated SQLite and 32 browser
  checks passed, including PDF/JPG/PNG requests, cancellation, repeat clicks and
  retained-upload recovery. Narrow-phone light/dark screenshots were inspected.
  Python/JavaScript syntax, Django configuration and diff checks passed.
- Deploy the versioned code/static assets normally; no migration or environment
  change is needed. Production deployment, real Telegram/Drive upload and
  PostgreSQL were not exercised; this is not a full-repository test run.

## 15 October 2026 - Payment preview reference

- Payment previews identify the payment with Payment No., rather than showing
  an HB/Eco source order number in the header. Drafts show Not assigned until
  normal workbook generation allocates the official payment number. Source
  order numbers remain on individual rows; order previews are unchanged.
- The Portal script version is bumped for normal deployment. No migration,
  financial-number allocation or saved document is changed by this UI fix.
- Verification: all eight new real-button/renderer HB/Eco checks passed at
  320px and 1280px; screenshots inspected. Broader finance browser checks:
  21 passed, one unchanged invoice-label assertion failed (expects "possible
  duplicate invoices" rather than the current "duplicate invoices"). JavaScript
  syntax and diff checks pass; production deployment was not performed.

## 15 October 2026 - Origination document downloads and unsigned completion

- Download the combined application, Main LAF or an individual selected
  supporting document from one compact chooser. Signed individual copies use
  verified original pages; unsigned validation is scoped to the chosen document.
  Incomplete-copy confirmation, current access and expiring revision-bound
  links remain enforced. Old combined links remain compatible.
- Published signature-free Main LAFs are available to new applications. Selected
  documents own their signer requirements; old product mirrors cannot add back
  removed signers. Independently published replacements no longer leave stale
  product maintenance notices; genuine pending changes remain pending.
- New applications without required signatures finish as Completed, not
  Approved. Completion validates and locks the application without signing
  sessions or provider calls. Supporting-document signing obligations and
  historical applications remain unchanged.
- Migration 0008 adds the completion status. Deploy it with the normal migration
  step and versioned static files. No manual seed or role command is needed.
  No production deployment or external provider write was performed.
- Verification: 170 affected backend tests passed on isolated SQLite; two
  PostgreSQL-only concurrency checks were skipped. All 59 browser checks passed,
  with mobile/dark/desktop screenshots inspected. Django, migration drift,
  Python/JavaScript syntax and diff checks passed. The artifact audit retains
  17 unchanged HEAD hash mismatches; the full repository suite was not run.

## 15 October 2026 - Origination cards and unsigned document publication

- Origination application cards show full IDs and dialable phone numbers for
  users already entitled to full case access. Explicitly restricted views remain
  masked; Portal and the independent Mini App role policies are unchanged.
- Cards use a compact, aligned identity/status layout with clearer dark-mode
  links. Removed competing card overrides and the repeated queue heading/count;
  Settings remains at the right of the header.
- Documents can publish without signers or with optional signers only. The
  editor explicitly says "No signatures required" instead of warning to add a
  signer. Editable-copy changes preserve the original published layout and
  historical application/signing requirements; publication is not loan approval.
- Verification: 127 focused backend tests passed on a freshly migrated SQLite
  database; one PostgreSQL-only test was skipped. All 46 browser checks passed;
  mobile, dark-mode and desktop screenshots were inspected. Python/JavaScript
  syntax, Django configuration, migration drift and diff checks passed.
- The broader non-OTP audit does not give production sign-off: interrupted
  evidence uploads, ordinary cancellation, queue scaling and deployed recovery
  still need work or verification. Baseline failures and real Admin journey
  limitations are documented in
  `docs/audits/origination-readiness-2026-10-15.md` and `KNOWN_GAPS.md`.
- Deploy the versioned code/static assets normally. No migration or environment
  change is required. No production deployment or provider write was performed.

## 15 October 2026 - Routine confirmations and immediate IT settings

- Portal uses one compact confirmation for routine invoice actions and removing
  a case from an unsigned payment. Cancel makes no change. Identity evidence,
  actual corrections, uploads and financial decision comments remain inputs.
- Withdrawing a sent invoice-name request confirms that HB was notified; staff
  no longer type a communication reference. The invoice hold and history remain.
- A saved SysUp product label no longer shows an internal catalogue-mapping
  warning in payment readiness. Ready cases can be selected and added without a
  global product version; actual invoice, order and approval checks remain.
- Authorized TAT IT saves settings immediately, retaining validation and audit
  history. Replays cannot change the setting/group/values, and stale pending
  changes cannot overwrite a newer save. Other apps' roles, access-grant review,
  and business/payment/signing approvals are unchanged.
- Verification: 184 backend checks passed; the two existing payment-document
  failures listed in `KNOWN_GAPS.md` remain. All 15 browser checks passed, with
  mobile/desktop light/dark screenshots inspected. JavaScript syntax, Django
  configuration and migration-drift checks passed. See
  `docs/runbooks/portal-action-confirmations.md` for scope and rollout limits.
- No schema, dependency or environment changes. No production deployment or
  provider writes were performed; PostgreSQL and Telegram-device checks remain.

## 15 October 2026 - Accurate Origination SMS feedback

- Signing invitations and verification codes require confirmed provider
  acceptance and a message ID. Rejected or malformed responses no longer appear
  successful; repeated failed requests do not send another SMS or claim success.
- Sent, Submitted and Buffered are awaiting delivery, not proof of receipt.
  Delayed intermediate reports cannot erase a final delivery/failure result.
- Signers receive a clear retry/contact-officer message when a code's send
  cannot be confirmed. Delivery reports still never sign or approve anything.
- Verification: 119 focused tests passed; two PostgreSQL-only concurrency tests
  were skipped on local SQLite/Python 3.14. Python compilation and diff checks
  passed. Ruff was unavailable locally; Python 3.12/PostgreSQL and live carrier
  checks remain unverified.
- No schema or environment changes are required. No credentials were changed,
  paid SMS sent or production deployment performed. Deploy the code, then run a
  separately authorized live SMS check before broad production use.

## 15 October 2026 - Portal invoice corrections and payment controls

- Payment preview/cancel are compact header icons; case search and Close share
  one row, including narrow mobile screens.
- Corrected uploads offer confirmation before payment. National ID must match;
  name differences warn, while phone differences retain verification notes.
  Deleted/superseded invoices are omitted and writes recheck scope/revisions.
- Unmatching also closes that invoice's unfinished correction, retaining its
  letters/history. Unsigned payment reviews/workbooks become stale; signed
  payment evidence cannot be changed through matching/unmatching.
- Duplicate selection/deletion now requires every captured invoice business
  value to match. Partial identity matches remain informational suggestions.
- Confirmation forms retain notes after failure and suspend background panels.
  Letter downloads refresh authorization/expiry, preserve the actual filename,
  and fall back when Telegram's download method is unsupported.
- No invoice schema migration, production provider write or deployment was run.
  See `docs/runbooks/portal-invoice-corrections.md` for verification and limits.

## 15 October 2026 - Actionable Mini App recovery

- Added compact, ten-entry App status lists to Portal, TAT, Complaints and
  independent Origination Settings, with confirmation, status checks, recovery
  guidance and copyable support references. Underlying forms/filters stay open.
- Portal's bell retains Sheet retry actions. System readiness explains missing
  template repairs; invoice cleanup retries now select one existing file update.
- TAT IT can retry Sheet updates/remarks within its complete grant scope.
  Group-wide target sync remains unavailable to branch/product-only IT grants.
  Signature/notification authority and all four apps' independent roles remain.
- Complaint Sheet retries have a leased replay receipt. No recovery recreates
  a comment, approval, payment, signature or report submission. Scheduled email
  recovery checks the existing delivery rather than sending another copy.
- Core migration 0205 provisions the reviewed TAT default and refreshes policy
  versions; normal deployment is required. No production deployment/provider
  write was performed during implementation.

## 15 October 2026 - Portal isolation and compact Performance

- Portal Home and the bell now show only Portal-owned background failures.
  Origination, Complaints and TAT failures remain with their owning workflows.
- Performance follows TAT Recognition's compact, header-free standings, with
  aligned scores and rank arrows. Removed obsolete dividers beside the numbers.
- Score details group the six milestone contributions into a compact two-column
  view, with scoring guidance behind the shared help control.
- Branches can list cases awaiting their first JBL visit, ten per page, using
  current Portal permissions and filters. This live backlog earns no points and
  never changes a settled period's result.
- Versioned Portal assets require the normal deployment; no migration or new
  environment setting is required. No production deployment was performed.

## 14 October 2026 - Origination usability, signature assets and JBL Apps

- Signature fonts now ship with their hash manifest; the build verifies and
  renders all four styles. Missing assets return clear retryable feedback.
- Application PDFs support incomplete copies after confirmation, while invalid
  values, signing requirements, current access and signed bytes stay protected.
  Filenames use applicant, product, requested amount and Nairobi time.
- Origination queue cards use aligned identity/status/detail rows; queue filters
  include existing applications even when their product is no longer available
  for new applications. Saved status remains narrow beside native actions.
- Signing rows use compact actions without decorative side stripes or
  section-wide click outlines. Preview navigation occupies opposite ends.
- Complaints graph selections reveal the successfully filtered table, matching
  the existing TAT/Portal behaviour and ignoring superseded requests.
- Added a permission-filtered JBL Apps chooser at `/apps/`. BotFather cutover and
  real-device download verification are documented in the deployment runbook.

## 14 October 2026 - Complaints email layout and reconciled figures

- Needs attention has its own full-width row; two complementary graphs share
  the next row, with equal desktop dimensions and stacked mobile layouts.
- Complaint introductions separate new complaints resolved in the same period,
  older resolutions, current reopenings and the overall open/overdue backlog.
- Email graphs use Mini App semantic colours, readable units, distinct axes and
  grid lines, line/marker trends, on-time/response doughnuts and age bars.
- Moved Data as of under the branding, kept period comparisons on one line,
  and removed the unrestricted All approved cases subject suffix.
- Changes affect new captures only. Frozen deliveries, permissions, workbooks,
  schedule settings and provider retry/idempotency behaviour are unchanged.

## 14 October 2026 - TAT BM action access and oldest-case names

- Oldest Active Cases leads with the customer's name rather than the reference;
  case-specific navigation remains accurate when names are duplicated.
- The built-in BM analysis capability no longer depends on currently available
  products or a cached catalogue. Migration `0204_tat_bm_analysis_capability`
  provisions missing TAT BM/IT defaults in the normal deployment release, retaining
  explicit denials, scoped grants and policy audit evidence.
- Recorded Mini App role independence in AGENTS.md. Origination grants, signing
  requirements and application history are unchanged. Existing TAT stage snapshots
  are not retrofitted; the stage remains an Approved/Declined decision with an
  automatic timestamp, not a signing prerequisite.

## 14 October 2026 - TAT remarks, clearer history and Telegram Web

- Remarks now append with the staff member, applicable TAT roles, Nairobi time
  and a clear separator. Accessible finished cases accept notes without changing
  their clock, stage, score or task state. Retries retain the same note once.
- The empty Add a remark composer retains failed input. Remarks use existing
  Activity; timestamp actions show one time, dropdown outcomes keep a compact
  value, and date corrections remain available under details.
- Stage rows separate elapsed time, target and result, with whole items wrapping.
- Reviewed Mini App HTML pages permit Telegram Web framing; Admin and unrelated
  pages remain protected. Authentication and scoped grants are unchanged.
- Native TAT Excel downloads supply a matching filename, attachment metadata and
  Telegram Web CORS, with named fallback and cancellation/pending feedback.
- Migration `0203_tat_event_role_attribution` widens saved role attribution only.
  After deployment use the existing `process_tat_notifications` runner for Sheet
  remarks. No new cron, environment variable or dependency is required.
  Rollback after checking actor-role lengths: `python manage.py migrate core
  0202_jawabufarmermaster_requisition_batch_and_more`. See ADR 0051.

## 14 October 2026 - Named Sheet columns and BM analysis approval

- Added the distinct BM decision after M-PESA submission for new TAT
  configurations. Approval advances to Admin verification; decline closes the
  case. Existing case paths, the later BM response, and final standings remain
  unchanged. Missing BM targets remain unrated; no credit-assessment gate is added.
- Added an explicit, idempotent Superuser rollout with draft-change detection,
  audited BM capability updates, and protection for shared Origination terms.
  The command previews by default; no product is automatically activated.
- Sheet addressing now uses unique normalized names across the Django adapters
  and supported maintenance scripts, with ambiguity and stale-header checks.
  Master metadata stays in its existing named columns rather than being moved
  to a fixed block. FarmUp imports reject duplicate names instead of renaming them.
- Optional audit-log publication verifies immutable event IDs on retries; duplicate
  case-index IDs stop publication. Order Sheet permissions require names rather
  than numeric/letter shortcuts. Disabled credit-assessment cards stay hidden.
- TAT creation commits independently of Sheet/Telegram delivery and reserves
  the existing durable dispatches. Retired the two superseded Apps Script web
  app copies as explicitly requested; their prior versions remain in Git.
- See the named-column/BM runbook for manual headers, script cutover and scoped
  activation. No production database, Sheet, Drive or Telegram changes were made.

## 14 October 2026 - Compact Origination applications and consistent signatures

- Application sections have Previous/Next arrows and a section picker; the header
  hides while editing, document icons share one row and saving feedback stays thin.
  Signing participants and expandable details have clearer controls. Withdraw is
  beside Signatures, with a short confirmation and no audit reminder.
- New typed marks offer four pinned handwriting styles. Preview and PDF use the
  same server-generated dark-blue PNG, keeping the whole name and verified date.
  Old captures/signed documents are unchanged. Ordinary unsigned downloads no
  longer receive red overlays; filenames and TEST markings remain explicit.
- Optional borrower/two-guarantor ID copies follow saved IDs. Front/back photos
  collate into one PDF; retake, preview and failed-upload recovery are supported.
  Existing editable drafts adopt on save; submitted requirements remain captured.
  Earlier copies are flagged if an ID changes, never silently reassigned.
- Django document choices show version labels. No migration, dependency, provider,
  permission or environment change; no production deployment or external writes.

## 14 October 2026 - TAT form alignment, search and simpler filters

- Paired form inputs stay aligned when labels, help or validation errors wrap.
  Messages remain beneath their fields without duplicated error lists or lost
  input. TAT opts into the shared presentation pattern; other apps keep their
  current layout. Dynamic fields and corrections use the same pattern.
- Queue search now includes branches and BRO names, using the same matching
  rules as Find Case. Full ID and Kenyan phone matching, visibility scopes,
  current queue, filters and ten-case paging are preserved.
- Shortened create/correction labels and removed repeated guidance. Report
  filters lead with common choices; specialist controls are under More options,
  with help beside Close and visible warnings for filters not affecting a graph.
  All stages remain visible; workflow rules and reporting calculations stay
  unchanged. No migration, dependency, environment change or deployment.

## 13 October 2026 - Clearer Origination signing and application copies

- Added application downloads: visibly unsigned before approval, exact signed
  PDF afterwards. Telegram confirmation names the file; cancelled requests are
  not reported as successful downloads. Expiring links recheck current scope,
  form completeness and revision; copy requests never create review evidence.
- Replaced the separate policy-page/activation requirement for new applications
  with a short, server-versioned signing acknowledgement. Draft adoption is
  audited. Existing packages, signing requirements and signed files are retained.
- Reduced filter noise to five status groups while preserving precise card
  statuses and the raw API for older clients. Signing rows are compact, show
  verified Nairobi dates and use plain-language document labels.
- Both previews share pinch, pan and page-swipe behaviour with compact controls
  in the requested order. Errors keep the preview open for retry. Toast feedback
  remains visible above dialogs and mobile keyboards.
- Alignment examples use realistic synthetic values and active choices. New
  signer settings pair signatures with Date signed fields; placement creates a
  non-overlapping companion where space permits. Missing placement is advisory
  at publication. Successful OTP/staff verification supplies the date to both
  the UI and PDF; retries retain the original timestamp.
- No schema migration, dependency, permission change, automatic republishing or
  production/provider operation. Published documents need an explicit editable
  copy to add date placements. Verification details and baseline limitations are
  recorded in `KNOWN_GAPS.md`.

## 13 October 2026 - TAT forms, personal tasks and trustworthy exports

- Removed routine queue freshness text/spacing without changing live timing or
  safe refresh. Added distinct create-form surfaces and aligned paired controls.
- Create/correction BRO selectors share the active roster, distinguish matching
  names, explain empty/error states and retry without losing entered corrections.
  Corrections resolve staff IDs server-side and preserve historical names.
- Personal task badges count unread assignments only. The panel has a right-
  aligned close button, ten initial entries, Load more and recoverable failures.
- Telegram Excel handoff names the file and reports requested/cancelled states,
  not false download completion. Older/failed native clients have a browser link.
  Download capabilities expire after 15 minutes and recheck current access.
- TAT workbooks omit Responsible Person, clarify stage/date/target headers and
  retain numeric heatmap percentages, colour and measurement context. Sheet
  minute formatting keeps the existing two-decimal values on normal/batch/repair
  publication. Cosmetic formatting failure never rejects the canonical save.
- Shared draft actions fill one row with green/red icons; file-free forms no
  longer request file reselection. New report subjects identify bot, Mini App,
  report, cadence and period/scope. Frozen email retries remain unchanged.
- No migration, new setting/dependency, production deployment or provider write.
  Test evidence and remaining real-device/account checks are in KNOWN_GAPS.md.

## 13 October 2026 - Compact, clearer complaint email reports

- Retained the 900px layout with short factual summaries, consistent mobile KPI
  tiles and one comparison line instead of repeated previous/sample messages.
- Added up to three complementary charts per complaint report, paired panels,
  compact table headings and full-width lone charts; no app links or new service.
- Whole-number rates, truthful short durations, explicit target-rated counts and
  long-resolution context explain differences between period tiles and daily charts.
- Chart labels use supported hyphens, bounded PNG layouts and unique inline IDs.
  Existing frozen deliveries and Excel/cohort/authorization rules remain unchanged.
- No migration or environment change. Screenshot checks use synthetic data;
  affected inbox duplication and real Gmail/Outlook rendering still need verification.

## 13 October 2026 - Placement-driven Origination forms

- Application forms show placed PDF fields and essential applicant, signing,
  lending and calculation details; empty sections and unused document steps hide.
- Main and supporting forms share server-owned visibility and required checks.
  Hidden answers remain recoverable without affecting active values or PDFs.
- New applications and editable PDF drafts use captured alignment; older submitted
  and signed applications are not converted. Document publication remains advisory.
- Alignment field lists explain whether an input appears in the form or remains
  necessary for signing/lending. No migration, new setting or provider call.

## 12 October 2026 - Clear signing acknowledgement and simpler emails

- Signing now ends with a dedicated server-confirmed acknowledgement and a
  cancellable ten-second countdown. External signing closes where supported;
  staff return to the application. SMS verification, consent, stamp and approval
  rules remain unchanged; failed/uncertain saves preserve input and recover safely.
- Admin role labels and compatible scope choices follow the selected Mini App.
  Origination roles require their own grants; no role codes or permissions changed.
- Restored the management email's 900px desktop width and removed introductory
  paragraphs and all app links. Kept attention, graphs, targets and directional
  comparisons; sample context now says "Based on 3 complaints" instead of n= jargon.
- Existing frozen email deliveries keep their original payload when retried.

## 12 October 2026 - Decision-first management email

- Replaced the wide dashboard-style email with a 600px computed headline,
  in-tile prior values/semantic Better-Worse changes, prioritized attention,
  one offline PNG and one top-five table. Removed empty/repeated body tables.
- Complaint summaries use actual targets, rounded days, target denominators,
  low-volume sample labels and consistent Nairobi date stamps; one-sample type
  medians are suppressed. Current backlog and unsupported comparisons remain
  explicitly separate, never reconstructed or fabricated.
- Added normal authenticated Reports entry links, scoped complaint drill-down,
  TAT task-link priority, dark-mode styling and readable blocked-image text.
  Customer facts stay in Excel/app; frozen retries and workbook bytes survive.
- Verified 125 report-delivery/complaint-timing tests on isolated PostgreSQL,
  then 80 final focused checks, 88 browser checks plus 13 final entry/design checks,
  JavaScript syntax and Node tests.
  Mobile/desktop light/dark screenshots were inspected; real inbox rendering
  and production deployment are not claimed.

## 12 October 2026 - Calendar report frequency and readable graph axes

- Added Yearly in shared Portal/TAT/Complaints email settings and Django Admin.
  It runs January 1 for the previous January–December, using Nairobi boundaries.
  Settings now explain each cadence's coverage and explicitly identify current
  backlog snapshots. Send now and preview retain the completed-period rule.
- Monthly complaint graphs show every day; quarter/year graphs show calendar
  months. Removed the confusing partial-week labels and the eight-point history
  clipping. Charts retain all selected-period facts, with daily/monthly units,
  visible axes/grid lines and whole-number complaint-count scales.
- Added calendar, scope, annual reservation/idempotency, workbook and rendering
  regressions plus mobile/desktop screenshot checks. Isolated the background
  wake-up in the existing request test so it cannot race PostgreSQL test cleanup.
- Migration `report_delivery.0006_yearly_frequency` changes choice metadata and
  a column comment only. Apply with `python manage.py migrate report_delivery`;
  pause/reconfigure yearly schedules before reverting code. No real email,
  production database, deployment or external service was changed.

## 12 October 2026 - Compact report emails and complaint comparisons

- Widened the shared email to 900px, paired compact panels and capped graph
  images at two. Category/branch rows combine labels, values and bars; successful
  graphs no longer repeat their data as tables. Plain text retains all displayed
  values, failed rendering falls back to tables, and Excel stays attached.
- Added Summary, Turnaround performance and Open-case follow-up to Complaints
  email settings. Existing schedules remain Summary; no schedules are activated
  automatically. One-off email retains the native filtered workbook.
- Added Nairobi previous-period and equal-elapsed comparisons, bounded history,
  sample sizes, explicit no-target/unknown-age handling and older open backlog.
  Captured reports and delivery payloads stay immutable across retries.
- Migration: report_delivery 0005 changes choices only. Reverse with
  `python manage.py migrate report_delivery 0004_reportdelivery_one_off`; pause
  focused schedules/pending deliveries before rolling back code. No production
  migration, deployment, real email or new external dependency was performed.
- Verified 108 focused PostgreSQL tests, 69 browser checks, JavaScript syntax,
  the Node suite and local migration reversal/reapplication. Inspected mobile
  and desktop screenshots, including aligned KPI cards and bounded graph axes.
  Real Gmail/Outlook rendering and the full repository suite remain unverified.

## 12 October 2026 - TAT and Complaints report clarity

- Separated TAT workload graphs from completed-performance graphs while keeping
  capability checks and legacy full-report responses compatible. Added compact
  chart-type icons and Day/Week/Month/Year controls for time-series graphs.
- Rewrote graph help to explain the measure, dates, targets and exclusions inside
  the existing question control, without repeating titles or visible paragraphs.
- Aligned TAT queue phone/ID values, removed repeated queue titles/counts and
  search headings, and grouped explicitly linked timeline changes without
  changing their underlying audit events.
- Restored Complaints' Reported vs resolved graph to reporting/closure dates;
  repeated closures count a complaint once per displayed period. Added scoped,
  data-backed Branch/Complaint type queue filters beside search.
- Standardized the Complaints settings icon, Village/Nearest Landmark and
  National ID wording. Sheet feedback has a visible separator with actor/time
  at the end. Confirmed saves/uploads trigger shared success haptics once.
- Added synthetic PostgreSQL, Node and screenshot-backed browser regressions;
  no schema, identifier rules, grants or external provider data were changed.

## 12 October 2026 - Configurable Origination signing

- Added opt-in product signing defaults and a compact, autosaving application
  Signers workspace in Django Admin. Documents define the available people and
  placements; active Superusers select optional participants and eligible staff.
  Multiple borrowers or staff sharing a role retain separate identities.
- New-policy applications go from Draft to Awaiting signatures to Approved.
  Submission prepares the documents automatically; the officer deliberately
  sends links. Everyone may sign in any order and the last required signature
  or stamp approves the exact packet. No Operations preparation or final-review
  screen is added to this flow.
- Retained legacy policies, consent hashes, sessions and signed bytes. Withdrawal
  retires signatures and links without deleting history. Current grants still
  enforce scope, assignments and distinct staff; configuration grants no access.
- Compacted the Mini App signing workspace and recipient ceremony, retained
  existing form scale, and added recovery after SMS failure. Signed documents
  remain reviewable; archival stays independent in the existing durable runner.
- Added migration 0007, database catalogue metadata, scoped testing-deletion
  ownership, PostgreSQL/concurrency tests and screenshot-backed browser checks.
  Production activation still requires a reviewed product and matching consent.

## 9 October 2026 - Origination field controls and input validation

- Added snapshot-owned email, integer, precision, date and dependent-location
  rules to the document field editor and main/supporting Mini App forms.
  Clearing a rule now removes it; shared fields intersect document limits.
- Validate supplied draft values and repeating cells on the server as well as
  inline in the form. Preserve existing font/spacing, incomplete drafts and
  entered values; no redundant top error list.
- Reviewed seed email/count/date controls and added replacement nationality
  choices from an offline 249-country reference, initially Kenya active.
  Re-seeding preserves activation decisions and existing application snapshots.
- PDF choice labels now include repeating cells; preview readiness checks use
  canonical codes rather than rendered labels. Fixed PostgreSQL row locking in
  draft canonical-field correction.

## 9 October 2026 - Selected testing deletion across Mini Apps

- Added one opt-in, active-Superuser Admin action for reviewed Origination,
  Portal, Complaints, TAT and SPIN records. A signed impact confirmation lists
  linked deletion and preserved history; no manual audit note is required.
- Configuration can retain operational history or explicitly remove its listed
  consumers. Selected evidence includes its owning workspace; unknown links
  block deletion. Stale confirmations roll back and duplicate requests replay.
- Preserved shared identities, access grants, raw ingestion, independent audit
  evidence and Drive files. Pending publication is cancelled by exact source;
  stale loaded cases cannot restore removed Sheet rows.
- Sheet cleanup starts after commit in a bounded background task, with durable
  status and Superuser retry in Integration operations. No cron was added.
- Added retired finance-number claims and two migrations so permanent deletion
  cannot recycle order/payment numbers, including after a counter adjustment.
  Documented the deletion and rollback boundaries in ADR 0044.

## 9 October 2026 - Published LAF attachment in guided product setup

- Published independent LAFs now appear in the product's document chooser even
  before product assignment. Explicit attachment validates compatibility and
  retains the exact published PDF/alignment instead of creating an unpublished
  copy. Existing applications and signatures remain unchanged.
- Catalogue rows now say "No products assigned" when that is the missing step.
  Selected-document cards update immediately after confirmed autosave, using the
  same server-rendered layout as the initial page.
- Added rollback, permission, stale-selection, retry and concurrent-attachment
  regression tests plus a synthetic real-browser Admin journey and mobile
  screenshot checks. No schema or environment change is required for this fix.

## 9 October 2026 - Origination testing, one-time LAF bootstrap and product deletion

- Release checks retain setup warnings without blocking safe deployment. Verified
  OTP availability uses the SMS provider configuration, independent of logging
  and release labels; authentication, consent/hash integrity and approval guards
  remain enforced. No new simulator or relaxed OTP limits.
- Added an opt-in release-stage bootstrap for eleven reviewed blank LAF drafts.
  It reuses shared-value seeds, never assigns products or publishes documents,
  resumes retained uploads and records a completion fingerprint that survives
  deletion. Explicit force is required to recreate completed seeds; no cron.
- Added hash-pinned private blank PDF deployment assets with author/XMP metadata
  removed and identical rendered pages. Corrected supporting-seed date/money and
  asset-table contracts to match existing canonical fields.
- Added testing-gated permanent selected-product deletion in Products Admin:
  one signed confirmation, no note, physical selected Product/Origination cleanup,
  atomic rollback and actor-bound retries. Other workflow references block the
  whole selection; shared documents, identities, compliance and external files
  survive. Background dispatches skip removed records.
- Retained and clarified the separate catalogue/tombstone removal action. Added
  ADR 0043, operator documentation and focused regression/concurrency checks.

## 8 October 2026 - Canonical Origination values across documents

- Added explicit version-2 field meanings and one shared application input per
  canonical value. Document-only inputs remain on their exact document instance.
  Existing applications, flat keys, signature rules and signed bytes stay unchanged.
- Added allowlisted Decimal calculations and authoritative workflow projections.
  Requested, contractual, approved and received amounts remain distinct; missing
  later events never become fabricated zero values or today's date.
- Validate compatible meanings, subjects, units, choices and visible table
  capacities before combining documents. Frozen signing packages retain exact
  per-document values; renderers reject overflow instead of dropping content.
- Added explicit person reuse for document-defined guarantor slots, content-bound
  retries and transactional shared/local saves. Deselecting a document retains
  its values without blocking the remaining active form.
- Added six unpublished supporting-LAF seed contracts, exact source fingerprints,
  per-LAF references and drift checks. Seeding is read-only unless explicitly
  applied; ambiguous wording and unsupported legal signers remain review tasks.
- Added the additive Origination field-metadata migration, ADR 0042 and the
  operator/rollout guide. Product and Document authoring remain separate.

## 8 October 2026 - Compact Complaints report controls and clear date cohorts

- Retained Date Type for cards/table and added Specific Quarter with Q1–Q4/year.
  Graphs keep their intrinsic date bases rather than changing with that control.
- Reported vs resolved now has two current-status series: Closed (+ve) and
  Open & Reopened (−ve), counting each reported complaint once.
- Replaced oversized chart-type text with aligned compact icons, removed Show
  cases, and moved immediate chart-selection feedback above search.
- Combined Total, Open, Closed, Resolution and On time into one compact KPI row.
  Help no longer repeats titles; duration tooltips show hours and equivalent days.
- Standardized graph date labels to dd-mm-yy across Complaints, TAT and Portal.
  Table dates and ISO filter keys are unchanged. New outcome/card timing fields
  are additive; legacy chart API fields remain available for older clients.
- Updated scheduled/one-off Complaint email labels to Complaints reported.
  No schema, dependency, access-policy or external-integration changes.

## 8 October 2026 - Shared form actions, media gestures and TAT chart selection

- Right-aligned TAT correction Cancel and Complaint draft status/retry controls.
  Recovery now says "You have a saved draft" with compact green Restore and red
  Discard icons, retaining established form typography and input sizes.
- Shared Telegram MainButton ownership across applicable forms in all four Mini
  Apps. Existing submission/validation handlers remain authoritative; disabled
  states, previews, bridge failures and in-page fallback actions are synchronized.
- Shared fixed-viewport image/rendered-page gestures: fit-to-5x focal pinch,
  bounded corner panning and page/file swipes only when fitted. Closing previews
  disposes their handlers, including Complaint and Origination adapters.
- Complaint type catalogue recovery retains entered data. Native type selection
  and dependent county/constituency dropdowns have touch/keyboard regression tests.
- TAT graph points select distinct, authorized contributing cases, preserving
  paging, filtered Excel and email exports. Multi-series clicks select the actual
  touched series; historical workload totals explain why case drilldown is absent.
- Verified 80 focused Playwright checks, 44 backend checks, all nine Node suites
  and syntax for 118 first-party JavaScript files. Synthetic screenshot coverage
  includes six viewport widths and both themes. No schema or dependency changes.

## 8 October 2026 - Independent Origination authoring

- Split commercial Product setup from independent Document authoring. Three
  non-linear Product tasks replace the stepper; selecting documents never forks
  them or publishes unfinished PDFs.
- Added draft autosave, server-confirmed save status and one Publish per workspace.
  Inline errors retain input; revision conflicts and content-bound retries remain.
- Added signer editing and packs, a standard lending-field shortcut, and a
  server-owned placement to-do list. Advanced geometry stays collapsed.
- Published documents offer an explicit shared update or one-product copy.
  Transactions preserve existing applications, approval policy and signed history.
- Added synthetic service and localhost browser journeys, screenshots and traces.
  No new models, migrations, settings or dependencies.

## 8 October 2026 - Restore form proportions and new-lead camera

- Restored established label, helper and input sizing across all four Mini Apps
  by removing the form pass's shared typography and minimum-height overrides.
- Removed repeated top error lists. Field errors remain inline with accessible
  associations and first-invalid-field focus; general failures retain one notice.
- Coloured draft Restore green and Discard red with light/dark semantic tokens.
  Validation, recovery data, required markers and workflow rules are unchanged.
- Fixed Create lead camera, gallery, preview and remove controls: these were
  incorrectly installed only when an existing case's draft recovery was wired.
- Added synthetic scale/error/draft/camera regression checks and refreshed asset
  versions so clients receive the corrected presentation and event handlers.

## 8 October 2026 - Shared Mini App form behaviour

- Centralized submission-time validation, linked field errors, summary focus,
  visible required markers and readable editable controls across Complaints,
  TAT, Portal and Origination, including dynamic forms and email settings.
- Added private seven-day field-only Complaint/TAT creation recovery using the
  existing draft store and current create permissions; no schema changes.
- Preserved complaint evidence for retry after canonical creation and prevented
  a delayed retry from clearing files selected for another complaint.
- Added synthetic browser viewport/error/recovery checks and draft scope,
  privacy, expiry and capability tests. Business rules and signing gates remain
  server-owned and unchanged.

## 7 October 2026 - Legacy Origination LAF catalogue compatibility

- Published legacy Main LAFs use their original product's immutable form and
  signer contract for catalogue compatibility and new application snapshots.
- Document versioning remains available after the owning product is retired.
  The catalogue offers an idempotent Create / open editable version action.
- Existing files, applications and published alignment are unchanged. Product
  eligibility and incompatible field/signer checks remain enforced.

## 7 October 2026 - Same-day Origination product replacement

- Guided setup can publish a linked successor on the same start date, retiring
  the previous version without deleting history or changing existing applications.
- Replacement and publication are atomic and audited. Unrelated overlapping
  versions remain blocked; no database migration is needed.

## 7 October 2026 - Two-tab Origination navigation

- Needs your action combines scoped corrections, drafts, legacy reviews and
  currently available staff signatures without duplicate application cards.
- Applications retains authorized visibility, search, readable status filters
  and ten-row pagination. Review alerts stay on the relevant application card.
- Workflow transitions, signing safeguards and historical queue API links remain
  unchanged. No database migration is needed.

## 7 October 2026 - Single-publish guided Origination setup

- Financial terms remain editable until final review. One transaction publishes
  both financial terms and the product profile, with full rollback on failure.
- Setup sections stay navigable; changed settings are review reminders rather
  than confirmation gates. Publication metadata no longer makes terms stale.
- Saves check relevant concurrency dependencies. Existing published terms can
  finish setup or use an editable successor; old Publish terms links go to review.
- No change to application approval/signing safeguards, models or migrations.

## 7 October 2026 - Shared report controls and focused TAT queues

- Portal and TAT report filters include month, quarter, year and date-range
  periods, shared with exports and emailed reports. County options and chart
  buckets consolidate capitalization and approved aliases without rewriting cases.
- Chart menus stay anchored; axes and tooltips identify counts, time, percentages
  and KES. Shared compact controls and email settings reduce layout drift.
- TAT queue search follows the selected role/all-case queue and current access,
  ignores stale responses, and preserves the query when returning from a case.
  Detail phones open the dialler; target-mirror health no longer claims success
  when work is pending and failed retries respect a cooldown.
- Invoice intake validates one invoice per file before Drive upload, allowing
  explicitly numbered continuations of that invoice and retaining upload recovery.
  Payment previews include verified continuation pages within the existing preview
  budget; historical collated files remain restricted to the selected invoice page.
- Document History cards are separated; Portal score details are more compact.
  Complaint national-ID text is centered in its badge, including six-digit IDs.
- Static asset versions refreshed. No migration or production-side action.

## 7 October 2026 - Compact orders, documents and shared phone actions

- Order selection keeps the number and date on one row, with Preview Form
  immediately below on phones and alongside on wider screens.
- Document History uses one compact list with aligned workbook and signed-copy
  actions, small icons and a green storage indicator beside the reference.
- Shared phone links cover displayed contacts in Portal, TAT, Complaints, SPIN
  and Origination, including dynamic phone cells. IDs, masked contacts and
  editable fields are not converted. Calling does not open the parent case.
- Presentation only: no workflow, permission, financial or database changes.

## 7 October 2026 — Invoice record layout

- Invoice actions share the available width evenly, with small icons, readable
  labels and a distinct delete action. Editing no longer removes its icon.
- Customer identity has a clear name/contact hierarchy; linked people appear
  before parsed fields, with readable IDs and wrapping names. Parsed fields
  are grouped into invoice details, amounts and balance checks.
- Empty action rows are omitted for read-only records. This is presentation-only:
  no matching, permissions, financial rules or database changes.

## 7 October 2026 — Direct order preparation

- Selecting approved cases immediately shows the order number, order date and
  Preview Form action. The extra Prepare order button is removed. Clearing the
  selection hides the section; selecting a different partner loads its number.
- Preview and final confirmation remain explicit; selecting cases does not
  allocate an order number or create an order. No migration or policy change.
- Queue filters use the shorter label Oldest cases instead of Needs attention first.

## 7 October 2026 — Compact Portal finance workspaces

- Document History groups metadata and signed-copy actions into compact rows;
  Orders/Payments and partner filtering share one toolbar. Details, retained
  versions and signed-scan replacement open on demand. Storage failures remain
  visible; routine successful storage no longer consumes a separate row.
- Invoice cards group customer and invoice identity, retain review warnings,
  omit empty phone placeholders, and keep selection/action touch targets at 44px.
- Editable payment batches keep Add cases above their members. One paginated
  search includes every authorized case state and explains unavailable cases;
  only payment-ready cases are selectable. Selection and payment mode survive
  searching/paging, and stale responses cannot replace current results.
- The new picker is scoped by payment preparation capability and exact batch
  group. Existing candidate callers keep their legacy response contract. Server
  addition also rejects inactive and previously paid cases instead of relying
  only on the picker to exclude them.
- No schema, financial calculation, approval policy or external-service change.

## 6 October 2026 — Portal signed agreements and consistent previews

- Editable payments retain their case search, including batches started from
  an invoice delivery. Other eligible cases may be added; active/completed
  payment membership and explicit Portal-group ownership remain protected.
- An accepted signed/agreed copy of the exact sent invoice-name letter clears
  the unchanged identity hold. Recording “sent” alone does not. Corrected
  invoices remain follow-ups; financial checks, current review, signed orders
  and payment finality remain mandatory. Original identities are not rewritten.
- Agreements retain private validated scan bytes, checksum, actor and exact
  identity evidence in the payments domain. Changed/revoked or superseded
  corrections cannot reuse that consent. Scoped Portal resets remove owned
  agreements before their protected letter artifacts.
- Needs review and Matched queues and their counts no longer overlap for held
  corrections. Cleared agreements remain visible in correction follow-ups.
- Portal previews share pinch zoom, swipe/page navigation and stale-view
  cleanup. Signed order/payment PDFs render bounded image pages rather than
  relying on a native WebView PDF frame; JPG/PNG scans remain supported.
  Complaints keeps its existing gesture controller without duplication.
- Correction dialogs align their Close/action controls; letter downloads name
  the file and give immediate feedback. The HB Send Reference input is removed.
  Letter previews constrain their tables/header to A4 width. Authorized
  Temporary Approval Cover is visible in Settings.
- Deploy the checked-in `payments.0007_invoicenameagreement` migration with
  these versioned assets. No deployment or live integration was performed.
  Policy and evidence-preserving rollback are in [ADR 0040](docs/adr/0040-signed-invoice-name-agreement.md).

## 6 October 2026 — Portal Operations workspaces

- Selecting cases shows a compact Prepare order action, not an automatic form.
  Proposed HB/ECO numbers are read-only and preview never allocates a number.
- Staff explicitly select an unsigned order for the same group, partner and
  request date to append cases. Every workbook version is retained. The exact
  current accepted signed scan locks the order; old scans cannot sign amendments.
- Confirmed unsigned order/payment cancellation releases cases and the number
  claim without deleting history, rewinding counters or invalidating credit/final
  approvals. The lowest explicitly released number can be reused. Batch UUIDs
  identify documents; ambiguous old number-only links fail safely.
- Invoice matching and new payment preparation require an exact signed current
  order. Historical financial evidence is preserved and has a read-only audit.
- Pending invoice deliveries omit empty/completed workspaces and support
  archive/restore without deleting invoices. Order details, invoice identities,
  Loan/Cash controls and action rows are more compact and consistently aligned.
- SysUp has inline candidate matching and per-field Keep Portal/Use SysUp choices,
  corrections, preserved source data, current scope/revision checks and retry
  protection. Supplemental data does not undo pipeline approvals; mismatched
  reviewed national IDs remain held. LGF stays separate from the JBL sheet deposit.
- Deploy migrations and versioned assets together. Deployment, PostgreSQL
  concurrency and real integration checks still require operator authorization.
  Migration, access-policy repair, legacy audit and exact rollback commands are
  in [ADR 0039](docs/adr/0039-unsigned-finance-workspaces.md).
- Local verification and outstanding broader-suite failures are recorded in
  KNOWN_GAPS.md; no production data or external system was changed.

## 6 October 2026 — Invoice upload confirmation and payment previews

- Invoice uploads await the authoritative response instead of inheriting the
  20-second queue/read timeout. Repeat submissions while uploading are ignored.
  Lost or unreadable responses advise checking Recent uploads; confirmed saves
  are not labelled failed if subsequent rendering fails.
- Payment-delivery invoice previews send the existing Telegram session header
  through Portal's shared API helper. Server authentication, scope checks and
  evidence-access auditing remain unchanged; no credential enters preview URLs.
- Deploy the versioned invoice/payment assets and shell together. No migration,
  setting, dependency, financial-data change or production write is included.
- Actual-module Playwright regressions cover slow success, repeated submission,
  connection loss, malformed responses, explicit rejection, rendering failure,
  bounded ordinary reads, authenticated preview, denial/retry and Back behaviour.
  Validation results and existing unrelated failures are recorded in KNOWN_GAPS.md.

## 6 October 2026 — Portal role views and review workflows

- Officers see read-only Orders; preparation controls remain capability-gated.
  No grant or saved capability policy is changed.
- Credit rejection/deferment no longer requires IMAB creation or approval-only
  product evidence, and never changes an existing system identity. Approval
  still requires IMAB and a customer number.
- Revisit filters current Deferred/Rejected outcomes within the viewer's scope.
  Expired deferrals remain visible; cash/other-partner withdrawals and progressed
  cases do not reappear because of old hold dates.
- Final Review has aligned repayment day/tenor controls, retaining legacy values,
  and an Approved-only READY FOR INSTALLATION & PAYMENT comment shortcut.
  Additional comments are preserved; the shortcut does not change a workflow status.
- Review documents have previous/next controls, a counter, photo swiping and retry.
  Close/Back preserves the review, cancels obsolete downloads and releases previews.
- Home uses a spinner and compact row placeholders; refresh preserves loaded work.
  Compact panel headings, camera captions, fixed Case History ordering and detailed
  street maps use the existing Portal components and providers.
- Credit comments reuse the existing voice workflow. Apply core.0201 and deploy
  the versioned assets together. Reversal: stop new credit dictation, resolve/expire
  outstanding attempts, then run
  `python manage.py migrate core 0200_alter_accesscontrolchangerequest_workflow_and_more`
  before restoring the prior code. The migration changes choices, not stored audio.
- Validation: 113 focused backend tests, 87 browser checks, JavaScript syntax
  and all Node tests pass using isolated/synthetic data. Screenshots inspected.
  Broader baseline failures and live-integration limitations are recorded in KNOWN_GAPS.md.

## 5 October 2026 — Readable report emails and static graphs

- Preserves the approved Jawabu design with larger Segoe UI font fallbacks:
  16px body/tables, 14px labels and 30px figures. Long amounts use wider cards.
- New Portal, TAT and Complaints emails embed up to three offline PNG graphs;
  full HTML breakdowns remain readable with blocked images or rendering failures.
  No unreliable interactive tabs, public links, new dependencies or migration.
- Excel bytes, scoped report facts and frozen retry payloads are unchanged.
  Actual Gmail/Outlook rendering remains an authorized operator check.
- Validation: 77 email-domain tests passed using isolated SQLite and mocked
  delivery; 29 Playwright checks passed. Mobile/desktop screenshots inspected
  for Complaints, TAT and Finance, including blocked images and long amounts.

## 5 October 2026 — Branded report email layout

- Report emails follow the reviewed Jawabu navy/green reference, using the
  existing logo as an inline image, aligned summary tiles and paired breakdowns.
- Mobile figures wrap into two columns; tables stack. Durations and percentages
  use concise labels and readable values without changing the source/export data.
- Retains JBL BOT sender naming, the Excel attachment, scope warnings and exact
  frozen retry payloads. No fake download URL, new dependency or migration.
- 69 email-domain backend tests and 28 browser checks passed; the final
  presentation helpers also passed a focused 7-test rerun. Screenshots inspected
  at 320px and desktop, including large Finance values and TAT durations.
- Local validation uses synthetic reports and mocked delivery; live inbox
  rendering and provider acceptance of the inline logo remain operator checks.

## 5 October 2026 — Compact Portal workspaces and decision reasons

- JBL Visit, Credit and Final Review use separate rejection/deferment reasons.
  Codes stay internal; Other reason requires a comment. Historical reasons and
  payment-review options are preserved, with server validation before visit uploads.
- FarmUp offers paged, read-only original source rows. Visit drafts retain the reason.
- Settings summaries, archive/document actions, invoice comparisons and Case History
  use compact Portal spacing. Routine invoice matching no longer asks for a review
  note; existing protected conflict confirmation still does. Chart grouping is in options.
- No schema migration or new dependency. Deploy the versioned assets together.
  Validation uses synthetic browser fixtures and an isolated SQLite test database;
  production PostgreSQL, live Telegram and external integrations remain unverified.

## 5 October 2026 — Branded report emails and filtered sends

- New report emails provide a JBL management overview with the detailed Excel attached; PDF attachments are removed. Bare sender addresses display as JBL BOT.
- Portal, TAT and Complaints report screens share a compact envelope dialog. Export-authorized users may send their current filtered report to one address without creating a schedule or recipient approval.
- One-off disclosure retains requester/destination evidence, idempotency, current-access checks, suppression and background dispatch. Download exporters remain the source for attachment structure and filtering.
- Apply report_delivery.0004; see report_delivery/README.md for the guarded reversal command. Live PostgreSQL, Gmail/Outlook rendering and provider sending require operator verification; no production emails or migrations are performed here.

## 5 October 2026 — Workflow-owned report email settings

- Portal and TAT Settings, plus a header Settings panel in Complaints, now let IT configure their own report schedules and recipients without Admin navigation.
- Shared delivery retains per-app recipient approvals, complete-grant scope checks, revision conflicts and idempotent background sends. TAT and Complaints adapters reuse their own report sources.
- Migration report_delivery.0003 assigns existing settings to Portal. Sending remains disabled by default; production migrations, PostgreSQL locking and live provider delivery require operator verification. See report_delivery/README.md for reversal precautions.

## Scheduled Portal email reports - 5 October 2026

- Added scoped approved recipients, daily/weekly/monthly/quarterly schedules,
  background Resend delivery, PDF/Excel previews and delivery history in Admin.
- Portal IT Settings can queue active report schedules immediately without
  waiting for email generation or delivery in the app.
- Retries retain exact payloads and provider keys; signed delivery events
  suppress bounced/complained-about destinations. Customer payload retention
  is 30 days and delivery metadata retention is 180 days.
- Sending remains disabled by default. Apply the reviewed new-app migration,
  configure verified-domain secrets/webhooks and provision the email runner
  before enabling it; no live emails or production migrations were performed.

## Activity value comparisons - 2 October 2026

- Portal case and invoice history, payment activity, Complaints history and
  TAT activity share compact old-to-new comparisons from recorded evidence.
- Recorded blanks remain distinct from unavailable historical values; long
  notes and larger changesets expand without duplicating actors or times.
- Payment changes and future Complaint/approval actions retain relevant prior
  facts in their existing audit records. Redactions omit comparisons and files.
- No historical event rewrite, schema migration or live external write is needed.

## Invoice cleanup, compact finance actions and chart controls - 2 October 2026

- Delete removes eligible invoice records; Ignore remains reversible. Payment
  and identity evidence are protected, shared PDFs are retained, and unused
  Drive PDFs have durable cleanup with explicit retry. Local deletion does not
  wait for Drive, and independent deletion audit evidence remains.
- Document history uses aligned preview/download/Drive icons. Payment cards
  and invoice-delivery actions are compact; each delivery invoice can be
  previewed without closing the preparation dialog or losing Cash choices.
- Complaints time-series charts share synchronized Day/Week/Month/Year
  controls. Filled chart bars and segments no longer have unrelated borders;
  line charts retain their series-coloured strokes.
- Synthetic mobile screenshots and PostgreSQL tests cover these changes.
  No schema migration or real external-service mutation is introduced.

## Portal shared controls and complete inbox - 2 October 2026

- Performance, score details, notification inbox and filter headings now reuse
  shared Portal layout rules: right-aligned controls, 44px touch targets and
  20px icons. Legacy screen CSS no longer overrides these components.
- The bell counts distinct authorized tasks and exposes all of them in pages
  of ten. Payment batches and import worklists each count once; overlapping
  grants cannot borrow another grant's branch scope for actions.
- Failed refreshes preserve the inbox, stale responses cannot replace newer
  data, and Escape/Telegram Back close it and restore bell focus. Existing
  Home sync-repair controls remain available.
- Full-shell synthetic browser tests cover six viewport widths, both themes,
  alignment, paging and visual regression baselines. Portal asset versions
  are bumped; no database migration or external service is added.

## Complaint history role colours - 2 October 2026

- HB history badges are red and JBL badges green, with readable light/dark
  theme colours. Unattributed legacy actions show Role unknown rather than Staff;
  actor names remain visible. No historical roles are guessed or rewritten.

## Complaints unified history - 2 October 2026

- Comment now has the same heading structure as Resolve, with voice input and
  independent drafts preserved. Saving feedback still leaves the complaint open.
- Removed the separate HB comments and Resolution History panels. Complaint
  History retains feedback, resolution and reopening notes in one place,
  including legacy resolution notes and authorized read-only register details.
- New history actions retain an immutable JBL/HB affiliation in their existing
  audit event. Older actions without reliable affiliation evidence show Staff;
  changing live access grants does not relabel past actions.
- Removed the redundant officer-source label. Sheet and export comments now
  contain the comment first, followed by the Nairobi timestamp and actor.
  Existing Sheet cells adopt this format on their next successful synchronization.
- No migration, environment setting, or live Google/Telegram write is required.
  Refresh existing Mini App sessions to load the versioned frontend assets.
- Verified: 92 of 94 complaint PostgreSQL tests passed on a fresh synthetic
  database; two stale National ID assertions remain documented in KNOWN_GAPS.
  The browser regression passed at 320/360/390/430px, with inspected mobile,
  dark and desktop screenshots. All nine Node groups, JS syntax and migration
  drift checks passed.

## Portal compact controls and document cleanup - 2-October-2026

- Performance filters and score details use compact, content-sized sheets with
  right-aligned close controls. Notification tasks scroll inside their panel.
  Secondary document actions use distinct preview/Drive icons with accessible labels.
- Queue contact numbers open the dialler without opening the case. Mobile paging
  shows previous/current/next instead of crowding the row. HB status pills share
  the available width; payment Refresh is right-aligned and order totals share a row.
- Document History partner selection now lives in a filter. Order invoice status
  uses actual matched counts rather than a missing upload-log message. Removed
  the two unwanted National ID/FarmUp helper labels without weakening validation.
- Duplicate selection works without first applying a duplicate filter. Bulk cleanup
  retains an original and protects payment/identity-change evidence; skipped items
  have specific explanations. Removal hides the invoice but retains audit evidence;
  existing Drive archival rules do not move a PDF with other active invoice pages.
- Signed-scan replacement requires confirmation, not a note. Previous scans stay
  retained, previews recheck access, and successful replacement does not replay
  installation release or payment completion. Late preview responses are discarded.
- Deploy migration `core.0198_physical_scan_replacement` with the new code, then
  refresh Mini App sessions. No environment variables or external setup changed.
  Do not roll back scan-status support after replacements without reconciling the
  retained superseded scans; never delete their evidence to make rollback fit.
- Verified: 77 focused PostgreSQL tests, 59 browser tests (including 320–430px,
  larger screens and light/dark Performance layouts), nine Node groups and JS syntax.
  Mobile screenshots were inspected. Broader pipeline failures are recorded in
  `KNOWN_GAPS.md`; live Telegram/Drive behavior was not exercised.

## Complaint HB comments - 2-October-2026

- HB staff can save timestamped resolution comments without closing a complaint,
  including voice input. Queue badges show the total comments; officers can read
  them. Comment and Resolve forms have separate drafts.
- Resolution Comments follows Resolution Details in the complaint Sheet and
  export. Insert that column in existing Sheets without replacing existing data.
  Comments publish as a complete canonical history; retry cannot append duplicates.
- Migration 0197 grants the separate comment capability to Complaint HB/IT and
  updates voice choices. Refresh existing sessions after deployment. Rollback:
  `python manage.py migrate core 0196_parsed_invoice_deleted_choices` then restore
  the previous code; existing comment audit records remain stored.

## Portal engineering remediation - 1-October-2026

- Locked integration claims now recheck terminal state, retry deadlines and
  remaining budget. Unique attempt tokens fence late successes/failures and
  publication failure evidence. The execution lease is shared with queue selection.
- New Sheet reservations bind to group/spreadsheet/tab, preserving FIFO inside
  each destination without holding up unrelated Master/Eco work. Changed targets
  supersede the old reservation rather than writing under the wrong FIFO claim.
- Assisted publication exposes its next retry and respects circuit cooldowns.
  Canonical saves remain independent of Google; no cron or hosted worker was added.
- Invoice retries resume retained Drive files and unfinished content hashes.
  New uploads carry a stable Drive recovery marker; ambiguous legacy acceptance
  requires reconciliation rather than an unsafe duplicate upload. Parsed rows,
  events and completion checkpoint are committed together.
- PDF parsing/preview use disposable, time-limited local processes. Delivery
  count/bytes, parser pages, preview pixel allocations and delivery continuation
  have explicit limits and actionable failure messages.
- Payment authorization, queue filtering and counts precede database pagination;
  only ten batches are serialized. Exact stale review digests remain actionable.
- Fixed direct-dependency/domain discovery and the five architecture-gate
  mutations; extended domain lint/coverage and added disposable PostgreSQL CI
  locking/upgrade tests. Pinned the installed psycopg version without upgrading it.
- EQ-06 invoice diagnostic privacy and EQ-11 broad maintainability cleanup were
  explicitly excluded. See the remediation plan for verification and rollout limits.

## Portal audit repairs - 1-October-2026

- Background Sheet coordination no longer counts as a foreground save. Its
  request times out after 20 seconds and releases the browser lease; canonical
  saves and the existing durable queue remain unchanged. No cron was added.
- New payment reviews bind to material payment facts, not the global case
  revision. Real financial/identity changes still require review and supersede
  generated workbooks. Existing historical digests are not migrated or restored.
- Commissioning cannot precede installation, including acknowledged early
  commissioning. Installation is permanently read-only in HB after commissioning.
- Payment comments and HB forms/notes now use shared unsaved-leave protection.
  Saving one comment preserves other unsaved comments; failed HB saves retain
  input and restore the Save button.
- Payment lists have scoped counts, payment-number search, 10-item pagination,
  filter/page-aware Back links and stale-response protection. Expanded case names
  wrap without shrinking the text.
- Corrected final-review queue null handling for legacy approved credit records;
  reconciled outdated test evidence fixtures and compact staff-facing labels.
- No database migration, access-policy change or production external write.

## Portal payment detail density and case context - 21-September-2026

- Rebuilt the payment-detail header and count strip to keep the batch total
  beside the payment identity and remove the separate full-width total tile.
- Payment rows now show the reviewed case context directly: case reference,
  customer national ID and phone, branch, loan officer, invoice, order,
  amount, repayment day, and payment mode. The existing case-detail link,
  approvals, return comments, cash switch and removal controls are unchanged.
- Approved cases remain behind one compact expandable section; redundant
  all-approved copy and a nested summary card were removed.
- Payment preparation now starts directly with search and compact candidate
  filters; repeated introductory copy, result-count chrome and the full-width
  Loan/Cash control were removed in favour of the accessible mode icon toggle.
- No migrations, access-policy changes, or external writes are required.

## Portal FarmUp review and navigation refinement - 21-September-2026

- Reworked the FarmUp review presentation into a compact, table-first mobile
  workspace: one search field, a compact review filter, grouped secondary row
  actions, a concise selected-row summary and a bottom commit dock.
- The current-file/mapping area now uses a small, readable setup strip rather
  than competing with the review table. Mapping, reconciliation, selected-row
  commit, and separate Sheet publication rules are unchanged.
- Reworked the FarmUp landing upload into a compact month, CSV-file and upload
  control group; the full review table now begins sooner on a small phone.
- Updated the Portal header with a compact JBL HomeBiogas brand treatment, a
  stable notification bell and an unobtrusive connection state that stays
  usable on narrow phones.
- No migrations, access-policy changes, or external writes are required.

## HB action, payment and SysUp review simplification - 21-September-2026

- HB Action installation now exposes only Not installed and Installed work.
  Historical Closed records are retained for audit but are hidden from active
  queues and cannot be edited.
- Commissioning search now occupies the released toolbar space when its
  installation-only filter is hidden. Completed payment cases collapse into a
  compact expandable list while pending and returned cases remain actionable.
- SysUp now lets a reviewer commit each selected matched row independently:
  safe nonblank source values update the selected case, missing or invalid
  values preserve existing data, unknown product names no longer block SysUp,
  duplicate source rows show as already current, and raw source rows are
  collapsed below the review grid.
- No migrations, capability changes, or external writes are required. Deploy
  frontend and backend together because the review presentation relies on the
  new server-side safe-update preview.

## Governed credit assessment inside TAT - 18-September-2026

- Added a bounded, revision-controlled credit-assessment workflow linked to a
  TAT case: statement matching, pre-appraisal evidence, manager authorization,
  analyst report/questions, BRO responses, analyst validation, and final Branch
  Manager decision.
- Added idempotent Gmail attachment intake, restricted Drive archival, encrypted
  short-lived statement passcodes, exact evidence hashes, maker-checker guards,
  append-only decisions/events, and a dormant future analysis-engine contract.
- Added a compact mobile TAT detail panel and an optional hard cutover that
  redirects/rejects legacy SPIN UI, API, and WhatsApp-import writes while
  retaining historical SPIN records.
- Requires migration `credit_assessments.0001_initial`, the pinned
  `cryptography` package, the dedicated personal Gmail address and authorized-
  user OAuth JSON, plus the existing service-account-backed media Drive folder.


## Portal order validation, finalization control and workbook download - 14-September-2026

- Order validation guidance survives the safe-message boundary and lists the
  affected customer and missing details in the preview. Template failures direct
  staff to IT while retaining internal exception diagnostics.
- Telegram shows one main Finalize Order action; browser clients retain the
  ordinary button fallback. Failed attempts retain their retry key.
- Workbook downloads use Telegram's native download or the system browser,
  matching the Complaints approach. Expired links direct users to Batches,
  never to regenerate or finalize an existing order.
- No migrations or settings changes; deploy backend and frontend together.
  Actual device downloads remain an operator verification step.

## Portal Case History inspection fix - 14-September-2026

- Opening Case History no longer starts a draft save that blocks its own
  navigation. Background visit, credit and final-review field recovery saves
  may finish during the retained-form detour; actual workflow submissions,
  uploads and ordinary page navigation remain protected.
- Case History and media buttons share aligned heights, margins and padding.
- No migrations or configuration changes. Refresh frontend assets after deploy;
  live Telegram WebView verification remains an operator check.

## JBL Visit guided document capture - 14-September-2026

- Separate Client ID, LAF and Supporting Photos sections. ID has named front/back
  slots; LAF has exactly two page slots, each with camera/gallery and review/retake.
- Server validates image content, corrects orientation and collates ID onto one
  PDF page and LAF into a two-page PDF using existing WeasyPrint. Supporting
  photos remain separate, with their own count and a combined upload budget.
- Forwarding requires all three evidence categories. Half-selected documents
  cannot submit; failed storage leaves the visit unlogged and captures retained.
- No schema or permission-matrix changes. Redeploy frontend and backend together;
  old unstructured LAF upload clients receive an explicit refresh instruction.

## Portal queue actions and case-inspection return - 14-September-2026

- Visit, credit and final-decision cards retain direct work forms. All Cases,
  Submitted Visits and Order Preparation cards inspect complete Case History;
  Order Preparation checkboxes and the main batch action stay separate.
- Case inspection retains the source screen, search, filters, scroll and open
  form in memory. Visible, Telegram and browser Back restore that context.
  Top-level screens still use full page loads. Cold history links use an
  allowlisted return screen; an action deep link is consumed once.
- Selection retains its captured revisions across rendering and inspection,
  shows selections outside the current page/filter, and optionally recovers
  IDs/revisions/date for 30 minutes within the same signed Telegram launch.
- Deferred review shows its reason and due date and offers only existing,
  authorized stage actions before reappraisal is due.
- No migrations, capabilities or external integration writes changed. Live
  Telegram-device validation is required before production release.

## Portal navigation, search, and visit camera refinement - 13-September-2026

- Removed the redundant top stage rail and mobile bottom hubs; the existing
  capability-filtered sidebar is the Portal's screen navigation.
- Standardized Portal search surfaces so the queue field renders one border
  across mobile and Telegram dark mode.
- Moved JBL visit capture into a dedicated camera sheet with multi-shot capture,
  review/retake, permission fallback, and stream cleanup. Selected evidence
  remains local until submission; closing with files now asks for confirmation.
- No workflow rules, authorization, schema, or external integrations changed.

## Portal full-page navigation reliability fix - 13-September-2026

- Switched Portal screen, stage, invoice, dashboard, and detail navigation to
  complete GET page loads after live reports showed that HTMX screen swaps
  could still leave Telegram WebViews on a blank or loading screen. Retained
  HTMX for navigation and in-screen data fragments only.
- Kept Telegram Back within an authorized Portal route, guarded unsaved edits
  and in-flight actions, and opened newly assigned orders in the current
  durable detail sheet. Added mobile browser and template regression coverage.
- No capability, workflow write, or schema changed.

## Portal screen navigation regression fix - 13-September-2026

- Activate Portal controllers from the newly rendered screen during HTMX swaps,
  even before browser history updates; navigation-only fragment refreshes no
  longer restart the current workflow. Restored correct active-state handling
  for four mobile hubs and bumped script cache keys for Telegram WebViews.
- Added browser coverage for an actual hub click and for the HTMX swap/history
  race. No routes, capabilities, workflow writes, or schema changed.

## Portal pipeline UI standardization - 12-September-2026

- Reorganized Portal navigation around the actual loan cycle: Intake, Field
  Visit, Credit, Approval, Fulfilment, and Finance. Mobile navigation now uses
  four stable Home, Pipeline, Cases, and More hubs while every route remains
  guarded by its existing capability.
- Added reusable Mini App workspace tabs, filter sheets/chips, feedback,
  pagination, single-flight action, list-state, and table-zoom primitives. This
  release adopts them in Portal only so TAT and Complaints remain visually
  unchanged until a separately reviewed rollout.
- Standardized Portal card queues on server-backed search, county, branch, and
  ordering filters before ten-record pagination. Search values remain
  memory-only; non-sensitive filters and queue position survive navigation.
- Added 20-200% report-table zoom and lazy loading for the vendored Leaflet map
  runtime. Removed the unused eager Chart.js download from the active Portal
  shell without introducing a CDN dependency.
- Recorded the navigation/component decision in ADR 0032. No workflow state,
  authorization rule, model, or database schema changed.

## Direct Superuser staff lifecycle and visible approvals - 29-August-2026

- Made active-Superuser staff onboarding, access changes, transfers, leave,
  return, and offboarding direct by default. The exact server-derived impact is
  reviewed before current-password confirmation; no checker is required.
- Preserved independent review as an explicit **Send for independent review**
  choice and added **Configuration > Staff approvals (N)** as the clear queue
  where eligible checkers approve or reject those plans.
- Added decision-mode and request-fingerprint evidence to lifecycle plans.
  Identical retries return the original plan/account; changed payloads cannot
  reuse the same request key, and raw passwords are never retained in the plan
  or audit trail.
- Added password-protected Superuser actions to apply or cancel existing pending
  lifecycle plans without waiting for a checker. Existing rows retain their
  original independent-review meaning after migration.

  Migration note: apply `core.0143_direct_superuser_staff_lifecycle`. Before any
  direct-decision rows exist it may be reversed to `0142`; afterward prefer a
  forward policy change so historical decision evidence remains interpretable.

## Superuser user hard deletion with retained audit - 28-August-2026

- Replaced Django's protected-object User deletion dead end with a full-width,
  active-Superuser-only impact preview and hard-delete confirmation. No checker
  is required; self-deletion and removal of the final active Superuser are
  rejected.
- Added immutable deletion batches and deleted-identity manifests. Live access,
  sessions, drafts, locators, and routing recipients are removed; active TAT
  ownership is force-unassigned and resulting coverage gaps are retained in the
  batch result.
- Preserved original compliance-ledger actor IDs and hash bytes through
  unconstrained historical references. Other protected history is retained via
  a disabled evidence tombstone rather than cascading business records.
- Fixed the browser confirmation POST so disabling the submit button for visual
  feedback cannot remove the confirmation marker and silently re-open the
  impact preview instead of deleting the selected accounts.
- Replaced the TAT open-task reverse join used during deletion with an
  existence-based row-lock query. This avoids PostgreSQL's prohibition on
  combining `FOR UPDATE` with outer `DISTINCT` while retaining transactional
  task rerouting.

  Migration note: `core.0142_user_hard_delete_audit` changes only historical
  User-reference constraints and adds the two evidence tables. Before any hard
  deletion has run, reverse with
  `python manage.py migrate core 0141_staff_lifecycle_workspace`. After a hard
  deletion has created orphan historical actor IDs, do not reverse this schema;
  restore an approved pre-deletion backup or ship a reviewed forward repair.

## TAT private-delivery reliability - 24-August-2026

- Fixed private TAT Telegram delivery on PostgreSQL by locking only the task-recipient row instead of applying `FOR UPDATE` across nullable profile and group joins. Due recipients now advance beyond `Pending` and record their delivery attempt.
- Made DM task locators one-shot Mini App navigation state. Back now restores the cached queue with a quiet background reconciliation, and Refresh updates the current view without reloading and refocusing the original DM task.
- Renamed the overlapping queue surfaces to **Assigned to me** for durable responsibility recipients and **Available to my role** for the broader capability-authorized work pool.

## Centralized TAT access and responsibility routing - 22-August-2026

- Added one Superuser workspace showing canonical TAT stage ownership, scoped
  user AccessGrants, role rosters, stage overrides, private-alert health, and
  configuration warnings without merging authorization and task assignment.
- Stage overrides now derive and lock their responsible role from the active
  TAT product configuration. Multi-role users are routed under the exact role
  required by the current stage; routine task delivery always requires a
  matching explicit TAT AccessGrant.
- Hardened routing with deterministic specificity, fail-closed ambiguity,
  recipient deduplication, strictly increasing ranked-backup SLA thresholds,
  safe shared-role/unassigned fallback, and append-only responsibility events.
- Added the canonical administrator/developer guide for multi-role grants,
  routing precedence, governed thresholds, Shadow-to-Hybrid testing,
  troubleshooting, migration, and rollback.
- Fixed responsibility Primary/Backup selectors so scope changes reload every
  exactly eligible multi-role user, explain empty results, and link directly
  to AccessGrant administration. The form now remains contained beside the
  open Unfold sidebar at desktop widths.

  Migration note: `core.0127_tat_responsibility_canonical_routing` adds the
  responsibility-event audit table and deactivates only conflicting or unknown
  legacy stage-specific routes for Admin review. It does not modify access
  grants, cases, Sheets, Drive, or Telegram. Before operational use, review the
  new workspace. To reverse a non-production application:
  `python manage.py migrate core 0126_tatprivatealertconnection_and_more`.

## SPIN and TAT Pilot data isolation - 22-August-2026

- Added independent, Superuser-controlled Pilot/Production modes for SPIN and
  TAT. New records retain an immutable creation-mode/cycle snapshot, while
  Mini Apps visibly identify Pilot data and reject stale writes after a mode
  or cycle change with a reload-safe conflict response.
- Centralized operational visibility so Production data and only the active
  Pilot scope reach live queues, Portal references, dashboards, repairs, SLA
  candidates, escalations, and daily metrics. Closed Pilot records remain
  Admin-visible and read-only.
- Added protected Pilot-cycle rotation and durable, resumable cleanup of closed
  cycles. Cleanup uses non-PII manifests, exact stable Sheet IDs, bottom-up row
  deletion, post-delete verification, row-pointer repair, concurrency locks,
  and formula/layout acknowledgements. Production/current-cycle records and all
  Drive/media objects are hard-excluded.

  Migration note: `core.0125_workflow_pilot_modes` classifies all existing
  SPIN and TAT operational data as Pilot, creates separate protected active
  cycles, and seeds a durable TAT case-number sequence. Applying the migration
  performs no Google Sheet, Drive, or Telegram side effect. Review both Admin
  modes before allowing new operational entries.

## Origination verified packet signing and Africa's Talking OTP - 21-August-2026

- Added revocable self-service and staff-assisted signer sessions for immutable
  Origination document packets. A signer reviews every page, draws or types one
  signature, accepts versioned atomic-packet consent, and verifies one OTP for
  all signature slots assigned to their role.
- Added fail-closed Africa's Talking Sandbox/production configuration, hashed
  OTPs, token/IP/phone throttles, attempt lockouts, informational-only delivery
  receipts, audited session reset/reissue, and Superuser-governed shared-phone
  exceptions. Raw OTPs and signing-link tokens are not stored.
- Added authenticated staff signature capture, governed production stamps, and
  retryable restricted-Drive archival of the exact retained signed PDF bytes and
  hash. The existing watermarked no-OTP simulator remains separate.

  Migration note: `core.0123_origination_verified_signing` adds Origination-only
  signing-session/challenge/throttle records and signed-package archival state.
  It does not dispatch SMS, upload to Drive, alter existing applications, or
  touch another Mini App. Keep `ORIGINATION_ESIGN_ENABLED=False` until Sandbox
  configuration and a controlled deployment test are complete.

## Workflow reliability test-contract repair - 04-August-2026

- Corrected Portal approval delegation so the documented active Django
  Superuser break-glass override is treated as all-branch authority, including
  when delegating an approval gate. The actor remains identified and audited.
- Updated workflow tests to assert the current contracts: immutable migration
  audit evidence may precede test events, invoice reconciliation reserves a
  durable register publication instead of blocking on Google Sheets, and each
  Portal role is offered only its permitted queues and saved views.

  Migration note: no schema migration, data backfill, or external integration
  action is included. To undo, redeploy the prior application commit.

## Portal report and import archival - 04-August-2026

- Added an Archive action to each saved-report card as well as the report
  detail page. Archive is non-destructive: the definition and immutable audit
  history stay retained, while the report leaves the active catalogue.
- Added an IT-only **Archive from Imports** action for staged FarmUp/SysUp
  uploads. It removes only the selected batch from the active Imports list;
  the original source, raw review data, Drive archive status and audit history
  remain retained. It never commits customer records or calls Drive.
- Fixed repeat entry/run of Reports failing with `render is not a function` by
  preventing route-load options from shadowing the Reports renderer.

  Migration note: `core.0100_portal_import_working_list_archival` adds only
  nullable archive metadata and an index; existing batches remain active and
  no backfill or external action runs. To undo a non-production application:
  `python manage.py migrate core 0099_portal_reporting`. Prefer a code rollback
  after production use so retained audit evidence is preserved.

## Portal Reports assisted live chart builder - 04-August-2026

- Reworked chart setup around the operational question: choose an approved
  comparison field, choose the measure, then choose from only chart displays
  that fit that data. Customer identifiers, names, phones, villages, and
  uncontrolled fields cannot become chart dimensions.
- Added a debounced, cancellable, branch-scoped live aggregate preview before
  saving. It returns at most twelve groups and never stores a report, emits a
  reporting audit event, or exposes case rows. Date trends now require an
  explicit Day or Month choice; crowded doughnuts clearly fall back to bars.
- Collapsed multiple chart configurations into compact, one-open-at-a-time
  cards so the active chart has room for its preview on a phone.

  Migration note: no schema migration is included. To undo, redeploy the
  prior application commit; saved reports, audit evidence, customer data,
  Sheets, Drive, and workflow state remain unchanged.

## Portal Reports mobile-density pass - 04-August-2026

- Reduced report-builder chrome on phones: a compact Step n of 3 indicator,
  tappable progress dots, and one editor action bar now replace the bulky
  segmented controls and competing bottom navigation.
- Made report field selection quicker to scan: categories have natural-height
  disclosures and selected counts, search filters the approved catalogue, and
  selected fields appear as removable chips.
- Compacted filters, ordering, and review; the chart editor now hides the
  irrelevant numeric-field selector for case counts and makes chart removal a
  secondary icon action.

  Migration note: no schema migration is included. To undo, redeploy the
  prior application commit; report definitions, audit evidence, customer data,
  Sheets, Drive, and workflow state remain unchanged.

## Portal Reports wizard step activation - 04-August-2026

- Fixed route-backed Filters and Charts/Review steps remaining on their loading
  placeholder: the Portal route signature now distinguishes the report editor
  step and therefore initialises each newly swapped root.

  Migration note: no schema migration is included. To undo, redeploy the
  prior application commit; report definitions, audit evidence, customer data,
  Sheets, Drive, and workflow state remain unchanged.

## Portal Reports wizard-route reliability - 04-August-2026

- Kept the live Reports controller mounted while moving between the Fields,
  Filters, and Review URLs. Those steps now reuse the already loaded local
  draft immediately instead of waiting for the report catalogue again.
- Bounded Portal route swaps to 20 seconds and show a clear retry instruction
  when a Telegram WebView navigation request stalls.

  Migration note: no schema migration is included. To undo, redeploy the
  prior application commit; report definitions, audit evidence, customer data,
  Sheets, Drive, and workflow state remain unchanged.

## Portal Reports mobile-first workspace - 04-August-2026

- Made the IT-only report builder operate as a phone-first three-step wizard:
  a safe-area-aware sticky action bar keeps Back/Continue/Save reachable, and
  Telegram Back now returns through setup steps before leaving the report.
- Made live charts defer rendering until they are near the visible viewport,
  adapt their height on Telegram viewport changes, use Telegram theme colours,
  and support ordinary touch interaction. Category-heavy bar charts use a
  horizontal layout for readable labels.
- Added compact phone result cards with the first report fields visible and
  remaining selected fields under an explicit More fields disclosure. Wider
  layouts retain the full, fixed-number-column table and XLSX export.

  Migration note: no schema migration is included. To undo, redeploy the
  prior application commit; report definitions, audit evidence, customer data,
  Sheets, Drive, and workflow state remain unchanged.

## Portal Reports recovery and live-rule reliability - 04-August-2026

- Made Reports route loading and live-result execution settle into a visible
  error-and-retry state if the client, network, API, or a stale screen swap
  fails. A single Chart.js rendering problem can no longer block the report
  rows or leave the screen on an indefinite loader.
- Made report filter/operator and ordering changes persist immediately in the
  browser draft. Date filters for Created at and Last updated now compare the
  selected calendar day rather than only midnight, and numeric ordering is
  covered by regression tests.
- Preserved live report availability when an old invalid chart configuration
  exists: the chart is marked for IT review while the approved rows remain
  available.

  Migration note: no schema migration is included. To undo, redeploy the
  prior application commit; report definitions, audit events, customer data,
  Sheets, Drive, and workflow state remain unchanged.

## Portal import source-preserving review - 04-August-2026

- Changed the IT-only FarmUp and SysUp review table to display the retained
  uploaded columns and values in their original order. The table no longer
  injects a number, status, match, cleaning, or other derived review column;
  import/archive state remains outside the source data.

  Migration note: no schema migration is included. To undo, redeploy the
  prior application commit; staged imports, source archives, customer records,
  and workflow state remain unchanged.

## JBL queue loader recovery - 04-August-2026

- Made the JBL Visit Queue load one server-rendered queue fragment instead of
  first fetching and serializing the same queue as JSON, then fetching it
  again as HTML. Queue cards now omit approval and evidence metadata that is
  only needed after opening an individual case, removing the per-card query
  fan-out from list rendering.
- Added latest-request protection so a delayed search/filter response cannot
  overwrite a newer JBL queue request or strand the current list on a loader.
  Timed-out/failed loads continue to show the visible Retry state. Bumped the
  Portal asset versions so Telegram WebViews receive this loader immediately.

  Migration note: no schema migration is included. To undo, redeploy the prior
  application commit; no customer, visit, approval, Sheet, or Drive data is
  changed.

## Portal Reports guided workspace - 03-August-2026

- Reworked the IT-only Portal Reports workspace into a searchable catalogue,
  focused definition detail page, and a three-step route-backed editor:
  approved fields, filters/order, then charts/review. This keeps reports
  readable on phones without changing the controlled reporting catalogue,
  access checks, branch scope, audit events, or report APIs.
- Added browser-session-only editor drafts so an unfinished definition survives
  normal movement between setup pages but is neither saved nor audited until
  the final Save action. A changed server version discards the stale local
  draft rather than overwriting it.
- Made live-result tables keep the opaque `No.` column fixed while horizontally
  scrolling, preventing header and row text from showing through each other.

  Migration note: no schema migration is included. To undo, redeploy the prior
  application commit; saved report definitions, audit evidence, Sheets, Drive,
  and customer/workflow data remain unchanged.

## Portal loader recovery - 03-August-2026

- Made Portal JSON and queue-fragment requests time-bounded. A stalled or
  failed mobile request now resolves to a clear, recoverable error state rather
  than leaving queues, invoices, or payment candidates on a permanent loader.
- Added an in-place Retry action for operational queues and ensured Invoice
  loading is always unlocked after an unexpected request/render failure.
  No workflow, financial, access-control, customer, Sheet, or Drive data
  changed.

  Migration note: no schema migration is included. To undo, redeploy the prior
  application commit; no persisted data is affected.

## Portal Invoice workspace drill-down - 03-August-2026

- Reorganized the Portal Invoice experience into focused nested pages for the
  reconciliation inbox, matched invoices, ignored invoices, uploads, and an
  individual invoice record. The default view now shows only records requiring
  a decision rather than mixing uploads, all statuses, and full audit detail.
- Kept existing invoice parsing, matching, unmatching, ignore/restore, bulk
  review, payment-readiness, Drive-source, and audit-event behaviour intact.
  No financial or customer workflow data changed.

  Migration note: no schema migration is included. To undo, redeploy the
  prior application commit; parsed invoices, upload batches, and audit history
  remain unchanged.

## Portal Reports drill-down - 03-August-2026

- Split the IT-only Portal Reports workspace into ordinary nested pages for
  the catalogue, saved-report detail, editor, and live results. Phone and
  Telegram Back now return through those pages instead of forcing the full
  builder, charts, and table onto one crowded screen.
- Preserved the existing report field catalogue, capability checks, live-run
  audit behaviour, and XLSX export. No customer/workflow data, report schema,
  Sheets, or Drive data changed.

  Migration note: no schema migration is included. To undo, redeploy the
  prior application commit; report definitions and audit evidence remain
  unchanged.

## Portal navigation and layout foundation - 03-August-2026

- Reorganized the Portal navigation into role-aware sidebar groups: Overview,
  My work, Finance & documents, Cases, IT tools, and Account. Staff still see
  only the destinations their existing Portal capabilities allow.
- Reduced the mobile bottom bar to at most four role-relevant destinations;
  the complete authorized navigation remains in the scrollable sidebar.
- Made route navigation canonical for Dashboard cards, case-history drill-down,
  and retained workspace actions. Explicit Portal URLs now take precedence
  over stale local "last screen" state, improving Telegram and phone-back
  behaviour without changing workflow data.
- Added Portal semantic status tokens, a documented overlay stacking scale,
  shared labelled-value tile primitives, and wider reduced-motion coverage.
- Portal route changes now swap only the active screen fragment. The shared
  shell, filters, feedback, and workflow overlays remain mounted, preventing
  duplicate bindings and reducing mobile DOM weight without changing any
  workflow, customer, document, audit, Drive, or Sheets data.

  Migration note: no schema migration is included. To undo, redeploy the
  prior application commit; this does not alter customer, workflow, document,
  audit, Drive, or Sheets data.

## Table readability and numbering — 03-August-2026

- Standardized the staff review, Portal Imports, and Portal Reports data tables so their first column is always **No.** with visible, page-aware row numbering.
- Replaced transparent/inherited frozen-cell backgrounds with opaque Telegram-theme-aware surfaces. Sticky headers and the frozen No. column now remain readable while horizontally scrolling in either theme.

## Controlled Portal reporting workspace — 03-August-2026

- Added an **IT-only Reports** screen in the Portal. IT can create bounded live case reports from a reviewed field catalogue, apply validated filters/order, add constrained bar/doughnut/line charts, preview results, and export an XLSX workbook. No report operation writes customer, workflow, Google Sheets, or Google Drive data.
- Added a read-only relationship-inventory command, `python manage.py inspect_reporting_relationships --json`, to make model relationships visible before a future report source is approved. TAT, SPIN, complaint, raw-message, GPS, media, Drive, and audit payload data remain excluded from this first release.

  Migration note: `core.0099_portal_reporting` is accepted for merge and local/staging validation only. It is **not authorised for production application** until an explicit release approval. To undo a non-production application before use: `python manage.py migrate core 0098_portal_role_separation`. That removes only the report-definition/chart schema; the policy and compliance evidence remain append-only and must not be deleted or silently rewritten.

## Portal operational-role separation and technical break-glass — 03-August-2026

- Portal **Business Administrator** is now labelled **Head of Rural** and is limited to final/payment review, approval delegation, and authorised document sign-off. A new **Operations Administrator** role owns operational credit, orders, invoices, payment preparation, and document regeneration, without JBL visit logging or Head of Rural review authority.
- JBL Officers can view their own submitted JBL visits and the Orders queue, but cannot select cases, preview a batch, or generate a requisition. Credit Analysts can view JBL evidence for credit review without media-upload rights.
- An active Django Superuser is now the requested, auditable technical break-glass override for all Mini App capabilities and Portal branch scopes. This supersedes the earlier changelog statement that a technical Superuser had no Mini App bypass; ordinary Django `is_staff` users remain non-bypass technical-admin users.
- Physical requisition/payment sign-off policy can name both Head of Rural and Operations Administrator through the existing independent maker-checker request process.

  Migration note: `core.0097_document_signoff_approval_roles` and `core.0098_portal_role_separation` are not authorised for production application by this code change. Apply only through an approved release. To undo `0097` before multi-role policy use: `python manage.py migrate core 0096_portal_import_archives`. Do not blindly reverse `0098`; restore the prior matrix through an audited maker-checker request using its recorded before/after evidence.

## Django Superuser Access Grant override - 03-August-2026

- An active Django Superuser can now add, edit, activate, deactivate, or
  remove a staff member's Mini App Access Grants directly from the User admin
  page. Each immediate change remains recorded with before/after evidence,
  an applied access-control request, compliance audit event, policy snapshot,
  and a refreshed access-policy version. This does not grant the technical
  Superuser any Mini App role or bypass maker-checker controls for capability
  matrix, document-signoff, or TAT configuration changes.

  Migration note: no schema migration is included. To undo, redeploy the
  prior application commit; do not delete the direct-override audit evidence.

## Current requisition Drive links - 03-August-2026

- Generating a requisition no longer opens the temporary local Excel download.
  The Portal now waits for the bounded Drive publication attempt and opens only
  the current generated workbook's Drive link. While publication is pending,
  Batches clearly shows **Saving to Drive**; a failed attempt remains retryable
  without presenting an older workbook as the current version.

  Migration note: no schema migration is included. To undo, redeploy the
  prior application commit; generated workbooks already retained in Drive are
  not deleted.

## Portal Imports staging and source archive - 03-August-2026

- An IT-only **Imports** tab stages and reviews FarmUp CSV and SysUp CSV/XLSX
  files through the existing validated parsers. It intentionally has no Portal
  customer-commit control: staging changes no customer, case, order, payment,
  or Sheet record.
- FarmUp and SysUp now always resolve to the single configured **Jawabu
  HomeBiogas** workflow. IT no longer selects a Telegram group in the Mini
  App; a missing, duplicate, or out-of-scope configuration returns a clear
  server-side error before the source is staged.
- Every accepted Portal source retains bounded local archive metadata and makes
  a separate, durable Drive-archive attempt beneath the existing approved
  Shared Drive root, in an `Imports/YYYY/MM-Month/Batch_<id>` path. The Portal
  shows whether that archive is pending, retained, or needs attention without
  exposing a direct Drive URL.

  Migration note: `core.0096_portal_import_archives` has not been applied to
  production by this change. To undo after an explicitly approved migration:
  `python manage.py migrate core 0095_jawabucasecomment`. This reverse never
  deletes customer data, audit evidence, or Drive files.

## Portal final-review queue tabs - 03-August-2026

- Head of Rural Review now uses two direct, touch-sized tabs: **Orders** for
  final decisions before a case can move to Orders, and **Payments** for cases
  captured in pending payment files. The selected tab is retained across queue
  fragment refreshes and sends its server-validated stage with every request.

  Migration note: no schema migration is included. To undo, redeploy the prior
  application commit; this only changes the Portal presentation and queue
  selection control.

## Portal JBL Visit recovery drafts - 03-August-2026

- Unfinished JBL Visit fields now autosave to a private, verified staff draft as
  the officer types and when Telegram hides or closes the WebView. Closing the
  sheet or opening case history no longer clears unfinished work; only a
  successful visit completion clears the draft.
- The form restores the newest secure/server or device-local field copy when
  the case is reopened. LAF/photo file handles cannot be restored by Telegram
  or Android, so the form states clearly that evidence must be selected again.
- Draft reads and writes require the existing `portal.jbl_visit.write`
  capability and the staff member's branch scope. Drafts remain field-only,
  staff-private, revision-protected, and expire through the existing
  `MiniAppDraft` retention policy.

  Migration note: this reuses already-applied `core.0072_miniapp_drafts`; no
  new schema migration is included. To undo, redeploy the prior application
  commit. Existing recovery drafts are disposable and may be deleted through
  their normal seven-day expiry.

## Safer `/sysup` budgets and conditional GPS fallback - 03-August-2026

- The JBL Visit form now hides the GPS-unavailable explanation until location
  capture is unsupported, denied, unavailable, or times out. A restored draft
  shows it only when it contains a prior fallback explanation.
- `/sysup` now has configurable file, staging-row, and per-commit row limits.
  Oversized exports are rejected before expensive matching; approved rows are
  committed in safe chunks, and register publication is reserved for later
  bounded processing rather than calling Google Sheets inside the request.

  Migration note: no schema migration is included. To undo the code change,
  redeploy the prior application commit; no customer data migration is needed.

## Atomic JBL visit completion and Telegram viewport recovery - 03-August-2026

- A single JBL visit submission now carries its own evidence-link revisions
  through to the final visit transition. This removes the false
  "case changed" conflict caused by the submission's own LAF/photo links,
  while retaining rejection of a genuine concurrent case edit.
- Portal sheets now use Telegram's reported viewport height after Android file
  picker return instead of stale `100vh` sizing, preventing the blank native
  canvas below the fixed visit action bar.

  Migration note: no schema migration is included. To undo the code change,
  redeploy the prior application commit; no customer data migration is needed.

## Portal additive case comments - 03-August-2026

- `Additional Comments` is now a Django-owned, oldest-to-newest history of
  new human remarks recorded from the JBL visit onward. Each entry includes
  the Kenya-local timestamp, staff member, and responsible Portal function.
- Existing Sheet-only text is deliberately replaced on the next Django
  publication; it is not treated as canonical history. JBL visit, final
  review, rework, and per-case payment call-up comments are added only when
  the authorised existing workflow action includes non-empty text.
- The Master Data Apps Script warning-protects `Additional Comments` alongside
  `Current Pipeline State` as a backend-owned value.

  Migration note: `core.0095_jawabucasecomment` creates an empty append-only
  comment ledger and does not backfill or rewrite cases, Sheets, or Drive.
  It has not been applied to production by this change. To undo after an
  approved migration: `python manage.py migrate core 0094_alter_jawabuapprovalrecord_decision_and_more`.

## Master Data lifecycle publication - 03-August-2026

- Master Data can now receive Django's backend-owned `Current Pipeline State`
  without replacing the historical JBL visit, Credit, or Head of Rural
  decision columns. It distinguishes JBL reschedules/halts, the 90-day
  reappraisal rule, order/invoice waiting, payment processing, and payment
  finalization.
- Conditional approvals are retired from active Portal decisions. Credit and
  Head of Rural now accept only the supported through/defer/reject outcomes;
  conditional input from cached clients is rejected safely.
- `master_data_script.gs` now resolves its operational columns from row-3
  headers, so a manually inserted business column cannot shift dropdowns,
  formulas, duplicate checks, or formats into the wrong column. Deploy the
  script manually to a copied Sheet before production use.

  Migration note: `core.0094_remove_conditional_jawabu_decisions` changes
  Django choice metadata only; it does not rewrite stored case data. It has
  not been applied to production by this change. To undo after an approved
  migration: `python manage.py migrate core 0093_requisition_publication_retry_key`.

## Portal durable register publication - 31-July-2026

- Portal case changes now commit to Django before any Google Sheet publication.
  The Mini App makes one short, authenticated follow-up attempt per register;
  pending or failed work remains durable and visible instead of holding the
  free Render web worker through a full Sheets/Drive round trip.
- Requisition generation now saves the workbook locally and returns its
  protected download immediately. Drive publication is retried separately and
  exposes pending/failed status on the batch, while the same retry key safely
  replays the committed generation instead of creating a second version.

  Migration note: `core.0093_requisition_publication_retry_key` is code/local
  validation only until a separately approved production release. To undo it
  before dependent production data exists: `python manage.py migrate core
  0092_portal_maintenance_state`.

## Portal Mini App navigation safety - 31-July-2026

- Telegram Back now stays within the Portal. A cold/direct case screen with no
  Portal history returns to an allowed Portal queue instead of sending Android
  back to Telegram and closing the Mini App. Screen changes also clear stale
  Telegram BackButton handlers before registering the current one.
- Requisition previews now refresh the selected cases' server revision
  snapshot before enabling generation. A background queue refresh no longer
  causes a false “case changed while you were working” message; a genuine
  change after the preview remains blocked.

## Batch-only order assignment - 31-July-2026

- Orders can now be assigned only from the selected-cases checkbox panel in
  the Orders queue. Individual case cards no longer expose order number or
  requisition-date fields, and cached clients are safely directed to the
  batch flow without changing a case.
- Payment product is no longer accepted during order assignment. It remains
  controlled by the later system-export import.

## Portal in-app client-media viewer - 31-July-2026

- Signed LAF documents and JBL visit photos now open in a protected Portal
  viewer instead of calling Android's external Chrome/Drive chooser. The
  current Mini App and case remain open; every successful view remains
  access-audited. Older URL-only evidence is clearly labelled as unavailable
  for in-app preview rather than launching an uncontrolled external intent.
- PDFs are converted server-side into bounded, Portal-owned page images before
  display. This avoids Android Telegram WebView's blank PDF canvas and blocked
  Google viewer while keeping the original Drive file, workflow state, and
  access controls unchanged.
- Client media now also offers a separate `Open externally` action for phone
  download controls. It refreshes
  the attachment-scoped external link immediately before launch, while `View
  in app` remains the default context-preserving action.

## Portal queue and final-review usability - 31-July-2026

- Empty Portal queues now use a compact, consistent completion state rather
  than a large plain panel with a text-only `OK` marker. Queue messages explain
  the next expected work in staff language.
- Final Review uses a two-column mobile-friendly field grid where space
  permits. The phone action is a 44px high-contrast control with an enforced
  white phone glyph and `Call` label on Android Telegram WebView, and
  normalizes Kenyan `07...` numbers for the dialler.

## JBL visit evidence foldering - 31-July-2026

- Future signed LAF documents and JBL visit photos now share one permissioned
  `ID_<National ID>` folder inside the relevant
  `Jawabu/JBL Visits/YYYY/MM-Month` path. Human-readable names use `LAF` or
  `PHOTO`, `JBL Visit`, and the client National ID; customer names and
  internal category enums are excluded.
- Existing Drive evidence remains unchanged for audit continuity.

## Authenticated client-media opening - 31-July-2026

- Client-media links are now short-lived, case- and item-scoped links issued
  only after the Portal authorizes the media list. They open correctly through
  Telegram's external browser without dropping Mini App authentication, while
  retaining the staff access event in the audit trail.

## Focused Final Review and client media - 31-July-2026

- Final Review no longer shows unrequested decision-reason or approval-
  condition controls. It retains the operational decision, repayment, and
  after-call inputs only.
- The former LAF-only control is now Client media, showing the signed LAF
  document and JBL visit photo uploaded by field officers as separately
  labelled links.

## Reliable Head of Rural review switching - 31-July-2026

- The Final Review selector now carries its chosen decision/payment lens
  through the JSON request, htmx fragment fallback, and pagination links.
  Selecting payment review can no longer silently render the final-decision
  queue instead.

## Focused Credit decision form - 31-July-2026

- The Portal Credit form now contains only the analyst's operational inputs:
  credit decision, IMAB creation status, and IMAB customer number. The
  unrequested status guide, decision-reason field, and approval-condition
  controls no longer burden staff. Historical approval evidence is retained.

## Internal order-register reliability - 31-July-2026

- Internal order-sheet publication now converts Django `Decimal` values to
  JSON-safe numeric cells at the Google Sheets boundary, so a valid JBL visit
  is not rejected solely because it includes an HBG or JBL deposit amount.

## Atomic JBL visit completion - 31-July-2026

- Portal JBL visits now validate the form, LAF document and JBL visit photo in
  one retry-safe multipart completion request. Cached two-step upload/log
  clients receive an upgrade message instead of creating orphaned evidence.
- New LAF and photo uploads now attach to the canonical case using the same
  case-reference key used during storage. A forward visit missing either
  required multipart category is rejected before any Drive upload begins.
- Portal detail sheets now use the stable layout viewport rather than a
  JavaScript-measured dynamic height, preventing Android's file-picker return
  from leaving a blank area below the JBL visit action bar.
- On return from Android's native file picker, the Mini App now explicitly
  asks Telegram to re-expand its WebView; this fixes the native contracted
  canvas that CSS alone cannot cover.
- FarmUp imports can label an HBG-visited, unvisited case `JBL to Schedule
  Visit`; the conservative backfill command defaults to a dry run and never
  writes to Sheets or Drive.
- Portal queues now show temporary per-filter card positions, while IT has an
  audited read-only maintenance switch. The migration remains pending separate
  production-release approval.

## Mini App settings hub - 31-July-2026

- Portal, TAT, Complaint Cases, and SPIN now present settings as a compact,
  role-aware hub with a read-only account/access summary, dependable workspace
  defaults, and an app release/support section.
- The unimplemented Telegram digest/quiet selector is no longer shown. Existing
  stored preference values remain compatible, while mandatory operational alerts
  remain unaffected.
- Portal health and temporary delegation, and TAT's maker-checker configuration
  cards, remain visible only to their existing authorised roles. Private Portal
  workspace controls remain dormant while the private-workspace rollout is on
  hold.

## Portal workspace hold - 31-July-2026

- Private Portal saved views, pins, recents, and automatic case-open tracking
  are not rendered in the Portal Mini App for any role, including IT. Existing
  backend records and IT-guarded endpoints remain dormant for a future
  approved rollout; no workspace data was deleted.
- `IT` is now a controlled role choice in Portal, Complaint Cases, TAT, and
  SPIN. Django `is_staff` and `is_superuser` remain unrelated to Mini App
  access, and no additional operational write access was granted.

## Access-control bootstrap - 31-July-2026

- The Django Superuser is now the root technical access-policy approver and
  can appoint/revoke independent Access Control Checkers from the user record.
  Appointment/revocation require a reason and create immutable compliance
  evidence; they do not grant Mini App workflow access.
- A sole Superuser may use one explicitly reasoned, audit-labelled bootstrap
  self-approval only while no independent checker or different Superuser
  exists. Once a checker exists, normal maker-checker separation is enforced.

## Release safeguards - 31-July-2026

- Render's reviewed pre-deploy command now fails on any production-readiness
  warning, and the runbook includes a current Portal release-record template
  with explicit cumulative-migration and rollback guidance.
- The existing Django Sentry integration is now privacy-filtered: no request
  body, query string, headers, cookies, user identity, arbitrary context, or
  exception message leaves the application with an error event.

## Workflow integrity - 30-July-2026

- Workflow `ADMIN` has been renamed to `BUSINESS_ADMIN` across Portal, TAT,
  and SPIN. Django technical superusers now require an explicit scoped Mini
  App grant like every other staff member; legacy evidence remains unchanged.

- Portal, Complaint Cases, TAT, and SPIN now each have a personal Settings
  screen for saved workflow defaults, compact cards, and non-critical alert
  intent. Settings are user-owned and do not change workflow access.
- TAT additionally has a role-aware Settings screen: IT proposes target,
  future holiday, and branch/role escalation changes; a different Business Admin
  approves or rejects them. Stage target values are frozen at entry so
  approved future changes do not rewrite an in-flight SLA.
- TAT Settings now resolves the runtime Telegram group configuration to its
  database row before reading pending proposals or escalation rules, avoiding
  a settings-page server error for configured groups.
- TAT compact case cards now visibly hide secondary identifiers and timestamps
  in queues, provide an immediate preview before save, and preserve full
  details inside the opened case.
- TAT corrections are now explicitly update-only and retain one retry key for
  a failed/resubmitted correction. The new-loan form clearly distinguishes a
  separate loan from an existing case and shows exact National ID/phone loan
  context without blocking legitimate repeat loans.
- FarmUp review now requires a reason before an explicit additional unit is
  created. Additional-unit imports bypass the normal duplicate-key update
  fallback, allocate the next linked unit number, and record the reason in
  the case timeline.
- The TAT case screen now keeps technical audit/update rows out of the
  staff-facing interface. Workflow stages remain visible for operations;
  the append-only audit history remains available to authorized audit and
  administration views.
- Portal Settings now saves a staff member's landing screen, first work queue,
  branch lens, review list, compact-card preference, and non-critical alert
  intent. Business Admins additionally see safe document readiness and can
  issue or revoke audited, branch-scoped approval delegation for up to 14 days.
- Portal now has a private workspace: staff can save up to ten validated queue
  views, pin active cases, and return to their ten most recently opened cases.
  Saved views never bypass the holder's current scope; inaccessible or closed
  pins hide immediately, and convenience records are retained only for the
  documented bounded period.

## Reliability hardening - 30-July-2026

- Portal, Complaint Cases, TAT, and SPIN Mini App writes now accept a shared
  retry key while cached legacy clients remain supported until strict mode is
  explicitly enabled. Shared Google Sheets batch writes, Drive uploads, and
  Telegram launcher publishing leave redacted durable operation records and
  use bounded transient retry/circuit protection. Protected `/api/readiness/`
  reads stored status only; `probe_integrations` is manual and configuration-
  only unless an operator supplies `--execute`.

Migration `core.0084_integrationcircuitstate_integrationoperation` has **not**
been applied to production. It adds only local integration-operation/circuit
tables. To undo after an approved migration, export needed operation evidence,
then run:

```powershell
python manage.py migrate core 0083_complianceauditchainstate_complianceauditcheckpoint_and_more
```

This file records notable, user-visible and operational changes. Entries are
added while work is performed; deployment remains a separate, explicitly
approved action.

## Unreleased — 30-July-2026

- Audit & compliance: Portal, Complaint Cases, TAT, SPIN, document sign-off,
  and access-policy actions now project evidence into one append-only,
  hash-chained compliance ledger. Django Admin supports investigation filters,
  controlled CSV/PDF exports, and integrity verification; sensitive media and
  audit-log access/export events are recorded. Daily checkpoints are retained
  locally by an explicit command, while compliance-mailbox delivery remains
  disabled by default. No automatic retention deletion, external email, or
  production deployment is included.

Migration `core.0083_complianceauditchainstate_complianceauditcheckpoint_and_more`
adds the ledger, chain cursor, checkpoints, permissions, and a PostgreSQL
append-only trigger. It has **not** been applied to production by this change.
To undo after an approved migration, export required evidence, then run:

```powershell
python manage.py migrate core 0082_sheet_register_governance
```

- Render build reliability: the application build no longer runs `apt-get` in
  Render's read-only native build environment. The existing WeasyPrint PDF
  preflight remains, so a base-image library problem still fails clearly
  before deployment.

- Django startup and static collection are now quiet in Render builds: access
  catalog queries are deferred until their Admin forms are rendered, and the
  intentional django-unfold overrides of stock Django Admin assets no longer
  produce duplicate-file build noise.

- Sheets/Drive integration governance: Admin-managed publication contracts now
  define per-register header/field ownership, while explicit read-only audits
  record schema drift, row-pointer/value divergence, and media-root sharing
  posture without copying raw customer values. TAT duplicate-row cleanup now
  proves the surviving immutable Case ID after deletion and re-publishes the
  canonical case before it reports success; failed verification or re-publish
  is retained as failed local audit evidence.
  TAT publication contracts now resolve the runtime configuration by immutable
  Telegram group ID, so Mini App updates are not blocked by the in-memory
  `GroupConfig`/database foreign-key boundary.

Migration `core.0082_sheet_register_governance` adds the local contract and
audit evidence schema only. It has **not** been applied to production by this
change. To undo after an approved migration, export required audit evidence,
then run:

```powershell
python manage.py migrate core 0081_jawabuapprovalcondition_jawabuapprovaldelegation_and_more
```

- Portal approval and media integrity: credit, final-review, and payment-review
  decisions are now append-only, reason-coded approval records with 90-day
  validity, condition clearing, material-change invalidation, scoped temporary
  delegation, and a separate per-case payment review. A forward JBL visit now
  needs a LAF, a JBL visit photo, and captured location or a stated
  unavailability reason. New visit media uses a non-PII case storage reference
  and retrievals are auditable. `audit_jawabu_visit_media` reports orphan
  candidates without deleting or relinking Drive files.

Migration `core.0081_jawabuapprovalcondition_jawabuapprovaldelegation_and_more`
adds the approval/delegation/media-audit schema and seeds only
`portal.approval.delegation.authorize` for the current Portal `ADMIN` role. It
has **not** been applied to production by this change. To undo after an
approved migration, first export required approval/delegation/media audit
evidence, then run:

```powershell
python manage.py migrate core 0080_physical_document_signoffs
```

## Unreleased — 29-July-2026

- Documents & finance: generated requisitions and final payment workbooks can
  now retain an authorised, physically signed-and-stamped PDF/JPG/PNG scan
  without overwriting the Excel source. The scan and exact source workbook are
  hash-bound, Drive retries are auditable, and the responsible Portal role is
  maker-checker configurable. E-signatures remain intentionally disabled.

Migration `core.0080_physical_document_signoffs` adds retained payment source
bytes, document sign-off policy, append-only sign-off attempts/events, and the
Admin-only `portal.documents.sign` capability. It has **not** been applied to
production by this change. To undo after an approved migration, export any
sign-off evidence that must be retained, then run:

```powershell
python manage.py migrate core 0079_remove_workflowtatdailymetric_unique_workflow_tat_daily_metric_and_more
```

- Customer History and TAT: Portal and TAT now present a single internal
  chronological history for each case, including operational events, customer
  provenance, documents, decisions, corrections/redactions, accountable
  actors, and related customer units. Official SLA status now uses the shared
  Nairobi business calendar while retaining wall-clock time as context.
  Overdue work gains idempotent in-app escalation tiers and a dry-run daily
  trend snapshot command; no Telegram notifications or automated transitions
  are introduced.

Migrations `core.0078_businesscalendarholiday_and_more` and
`core.0079_remove_workflowtatdailymetric_unique_workflow_tat_daily_metric_and_more`
add the managed holiday calendar, append-only timeline annotations,
escalation accountability, and daily TAT projections with branch/role and
known-staff attribution. They have **not** been applied to production by this
change. To undo after an approved migration, preserve any required audit
evidence, then run:

```powershell
python manage.py migrate core 0077_seed_operational_products
```

- Jawabu data quality: `/sysup` and FarmUp now share governed customer identity
  normalization, retain historical phone observations, flag 7-9 digit ID
  exceptions for review, preserve system-export field provenance, and validate
  system products against one Admin-managed catalog. The Admin dashboard now
  reports active-case data-quality coverage and a dry-run command can audit
  active Jawabu cases or a staged `/sysup` batch without writing data.

Migration: `core.0076_governed_jawabu_data_quality` and
`core.0077_seed_operational_products` are required for governed phone history,
provenance, review evidence, and the product catalog. They have **not** been
applied to production by this change. To undo after an approved migration,
first export any provenance/review evidence that must be retained, then run:

```powershell
python manage.py migrate core 0075_tat_workflow_receipts
```

- Workflow integrity: Jawabu Pipeline and TAT now reject stale Mini App
  updates, record explicit transition metadata, preserve reasoned rework
  routes, and expose safe SLA-escalation dry runs. Payment approval behaviour
  and access-policy assignments are unchanged.

- Mini Apps: added shared touch-friendly controls, consistent status semantics,
  skeleton queue loading, Telegram haptic feedback, and session-only restoration
  of harmless Portal/Complaint queue context.
- FCA, FarmUp/System Export, and SPIN forms: replaced browser-local sensitive
  recovery drafts with short-lived, verified, server-owned field drafts. File
  attachments are intentionally excluded and must be selected at submission.
- Operations: added the shared glossary, ADR process, known-gap register, and
  repository operating standards for approvals, migrations, audit evidence,
  and release safety.

Migration: `core.0072_miniapp_drafts` is required before this recovery feature
works. It has **not** been applied to production by this change. To undo after
an approved migration, confirm drafts are disposable and run:

```powershell
python manage.py migrate core 0071_accesscontrolpolicystate_and_more
```

Migration: `core.0073_workflow_integrity`,
`core.0074_backfill_workflow_integrity`, and
`core.0075_tat_workflow_receipts` are required before workflow revision checks,
transition receipts, and SLA records work. They have **not** been applied to
production by this change. To undo after an approved migration, first export
any new transition/SLA audit evidence that must be retained, then run:

```powershell
python manage.py migrate core 0072_miniapp_drafts
```
# Report schedule editor recovery - 5 October 2026

- Report manual queuing, scheduled reservation and retry lock only their owned
  row, avoiding PostgreSQL's nullable-authorizer outer-join FOR UPDATE error.

- Fixed Portal email Settings' doubled API prefix and unpacked its actual
  response/error envelope. Browser regression now uses the real API client.
- Complaints header actions stay right-aligned on one row; Settings has a
  compact section divider, aligned fields and equal-width Save/Cancel actions.
- Removed the Group dropdown and replaced free-text Branch with scoped choices.

- Add report tolerates unavailable/restricted WebView crypto helpers, scrolls
  to and focuses the editor, and reports opening failures visibly. Regression
  coverage includes the actual Portal Settings shell with sending disabled.
# Immediate manual email dispatch - 5 October 2026

- Send now starts bounded, post-commit processing for its exact durable delivery
  IDs in Portal, TAT and Complaints; it no longer requires a shell command.
- Settings shows provider acceptance or a safe failure reason and wakes pending
  work on reopening. Unattended recurring schedules still require the runner.
