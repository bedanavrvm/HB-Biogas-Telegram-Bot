# ADR 0063: closed browser TOTP enrollment and one-time recovery handoff

## Context

The user authorized the next bounded phase after D13a. Branch HEAD is 144ed843;
production release/migrations remain unknown. Browser authentication is disabled
and its routes are unmounted. React/ADS remains held on exact peer/licence/asset
acceptance; backend prerequisites can progress without installing that frontend.
P1b.2a protects pending seeds but has no enrollment workflow.

## Decision

Implement P1b.2b.1 as three unmounted, POST-only, cookie/CSRF enrollment handlers:
begin, confirm, and one-time recovery-code retrieval. Require the existing active
user's current explicit admission and browser password-only channel, a fresh
password recheck through allauth, and server-owned enrollment context bound to
that admission revision and a client UUID request key. An ordinary Admin/Telegram
cookie, supplied Telegram/token credentials or completed company login cannot
enroll a replacement factor through this boundary.

Use the pinned allauth ReauthenticateForm, ActivateTOTPForm, activation flow and
recovery-code view/generation implementation. Do not implement OTP algorithms,
patch vendor code, alter global sessions or expose generic factor-management
routes. The existing request-local encryption adapter protects the transient
seed; permanent TOTP and recovery seeds use the existing encrypted MFA adapter.

Lock the existing staff user and admission for enrollment/factor writes. Record
begin, activation and recovery-view receipts in the existing compliance ledger;
failure to audit rolls back factor/recovery changes. No secret, URI, code or
credential hash is stored in audit. Retries cannot replace a factor or regenerate
codes. A valid same-key begin retries the same pending seed; activation retries
return the prior nonsecret receipt. Expired/lost pending context requires a new
begin; no new persistent model/schema/dependency is needed.

Recovery codes follow the vendor show-once policy. Retrieval and its audit are
transactional and serialized; a repeated request returns an explicit already-
viewed result without codes. Lost response does not prove delivery and does not
authorize a second disclosure or automatic regeneration. Staff with a working
authenticator can still log in; unsupported recovery/helpdesk escalation and any
approved reset retain the earlier lifecycle's verified support process.

Enrollment is not MFA login. It never issues business assurance, a workflow grant
or an allauth-login completion signal. After enrollment/recovery handoff require
an explicit logout and a new native password-plus-MFA login. The session bootstrap
may report nonprivileged recovery/reauthentication progress without returning
secrets. All business APIs remain absent and must later use the company-browser
guard plus owning workflow authority.

No email/message is dispatched by this dormant slice. If native account email
notifications are enabled, enrollment is held rather than silently suppressing
or triggering an unaccepted mail path. Provisioning, operational recovery UI,
shared native replay cache, mail/support, frontend acceptance and M1 remain gates.

## Consequences

No production URLs, UI, employee/password/address provisioning, factor replacement,
new grant, dependency, configuration variable or migration. Keep the global
browser flag false and activation checks blocking. Native reauthentication
timeout and existing pending-seed expiry both constrain enrollment; these are
security defaults, not measured service objectives. Competing pending starts may
invalidate/supersede browser-local state; confirmation must fail closed rather
than attach a stale seed. PostgreSQL race evidence remains required before use.

Normal rollback keeps the channel closed and preserves native factors/admission/
audit evidence. Do not reverse prior schema, erase credentials or restore a
database to undo this slice. Do not activate on the strength of local tests.

Implementation verification found that Django SessionMiddleware skips session
saves on 5xx. After audit rollback, explicitly persist cleanup of the current
browser's transient context. A concurrent/unavailable session database cannot
guarantee cleanup; return no credentials or assurance and retain current
admission/expiry requirements. This is not global session revocation.

## Alternatives considered

- Generic allauth account/factor API: exceeds the approved surface and can expose
  unrelated account/recovery operations.
- Enrollment grants business login: conflates setup with MFA authentication.
- Automatically re-show/regenerate lost recovery codes: defeats show-once policy
  and hides uncertain disclosure; retain an explicit support boundary instead.
- New employee/enrollment database: unnecessary for this bounded contract; use
  native credential rows, browser-local context and existing audit receipts.

## References

- codebase-analysis-docs/assets/STAFF_BROWSER_JSON_AUTH.md
- codebase-analysis-docs/assets/STAFF_BROWSER_LIFECYCLE.md
- https://docs.allauth.org/en/latest/mfa/adapter.html
- https://docs.allauth.org/en/latest/mfa/configuration.html
