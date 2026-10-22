# ADR 0073: independent channel experiences and browser Complaints parity

22 October 2026. Accepted for implementation by the user's approved plan.

## Context

The separate React/ADS browser currently has restricted native Complaint reads
and an isolated write simulator. Staff need real operational browser journeys,
shareable no-reload navigation and a professional desktop composition. Request
origin must be attributable without treating client headers as authentication.

## Decision

Retain one deployment and canonical Django state/business rules. Browser uses
company admission/password/MFA/cookie/CSRF; Telegram retains signed identity.
Implement separate versioned browser operational interfaces over the owning
Complaint services; retain the earlier restricted v1 read projections. Browser
case operations, evidence/capture, reporting, export/email, settings and recovery
must enforce their existing workflow capabilities, revisions and request keys.
The simulator is never an operational implementation or fallback.

A request-local channel context records attempted and verified channel,
workflow, request correlation and bounded release labels. Authentication owners
bind verification; a supplied channel/user-agent never grants it. Structured
request logs and new compliance metadata retain this context without customer
values, raw routes/query strings, credentials or proof. Historical audit bytes
remain unchanged. Async work can retain origin separately from execution.

Browser navigation uses a bounded History API module under /staff/app/.
Known major routes are shareable and reloadable without full-document navigation;
safe filter/selection state is restored, while sensitive search/form values stay
out of URLs and persistent client storage. Use actual ADS controls and a fluid
desktop work area; preserve Telegram appearance and existing independent roles.
No placeholder/development status or demo controls appear in the staff build.

Keep browser operational and auth release switches off until explicit release
acceptance. Demo configuration is false by default and rejected in production;
synthetic manifests/transports remain isolated local/restricted-staging builds.
Normal production URLconf remains unmounted while M1 is unaccepted. The closed
test URLconf exercises real native sessions and canonical services safely.

## Consequences

Channel-specific assets, adapters, switches and regression suites limit UI/auth
regressions; a shared process/database outage still affects both channels. No
separate deployment, new business grant, real provider delivery or production
activation is authorized. Reuse existing JSON audit metadata and domain models;
no schema migration is needed for channel attribution. Rollback switches browser
off and restores its previous immutable artifact without reversing records.

Each slice records executed checks and remaining parity in
docs/runbooks/browser-channel-parity.md. Evidence is synthetic, source-bound and
not automatic human design approval. Existing security/privacy/shared-cache/
support and real-device acceptance gates remain before real staff admission.

## Alternatives

Separate channel deployments were offered and declined in favor of a shared
deployment. A fixed URL was declined in favor of soft navigation with URLs.
Telegram-template reuse and a production demo/live data toggle were rejected:
they couple interfaces and risk presenting synthetic workflows as operational.
