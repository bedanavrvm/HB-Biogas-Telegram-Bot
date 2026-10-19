# ADR 0061: explicit browser admission and browser-only revocation

## Context

The user authorized the next manageable platform-independence phase after P1a,
while preserving Telegram. Production release/migrations remain unknown. P1a
distinguishes completed password/MFA login from ordinary Django sessions, but
has no explicit staff browser opt-in or browser-only revocation generation.
Deleting shared Django sessions or changing passwords to revoke browser access
would also disrupt existing Telegram/Admin sessions.

## Decision

Implement P1b.1 as a backend-only staff identity lifecycle boundary. Add one
bounded-domain `staff_auth.StaffBrowserAdmission` model with a disabled default,
existing-user link, retained original user ID, positive revision and timestamps.
No automatic backfill, accounts, passwords, verified emails or workflow grants.
Use the predictable `staff_auth_browser_admission` table, PostgreSQL comments,
constraints, deliberate reverse relationship and catalogue metadata.

Only a currently active Django Superuser may deliberately authorize, suspend,
revoke browser sessions or reset browser MFA through the service and dry-run-first
management command. This is technical identity administration, not a new workflow
role/capability. Each accepted action is revision-checked, actor/request-key and
payload bound, and transactionally recorded in the existing compliance ledger.
Failure to audit rolls back the action. MFA reset also requires a support
verification reference and removes factors without revealing their material.
The reference records an operator attestation, not automated identity proof.

Browser assurance captures the admission UUID/revision and cannot survive a
revision change, suspension or loss of the user link. Completed authentication
must have started after the latest admission change. Existing Telegram identity,
shared Django sessions, password hashes and workflow grants remain untouched.
Every future browser action still needs its owning workflow authorization.

Use SET_NULL on user deletion and retain the original numeric user ID for
investigation. Package-owned allauth email/factor rows are disposable credential
state under the already governed user-hard-deletion service; classify them
explicitly so adding allauth does not block that existing operation.
The registry also lacked the two expiring per-viewer recognition checkpoints;
classify those cache rows as disposable. Immutable settled period snapshots
remain unchanged and are not part of the deletion closure. Remove the new
admission model from generic Admin auto-registration, not just vendor editors.

## Consequences

P1b.1 is not usable login, enrollment, password provisioning or a recovery UI.
Browser admission remains globally off and activation checks remain blocking.
Pending secret protection, shared replay/abuse controls, mail, helpdesk ownership,
source-bound UI review and staging/production acceptance remain gates for the
next P1b slice. No external dependency or operational business rule is added.

The additive migration has no data backfill. Normal rollback keeps the browser
off and preserves admission/audit records. Before actual use and only with
explicit authority, `python manage.py migrate staff_auth zero` removes this
table; compliance ledger evidence survives. After use, prefer a reviewed forward
repair because dropping admission state loses the revocation boundary. Do not
run this reversal in production as part of implementing the phase.

## Alternatives considered

- Password changes or deleting shared sessions: rejected for browser-only
  revocation because they disrupt Telegram/Admin.
- Existing MFA enrollment alone: insufficient as an employee admission policy
  or an independent revocation mechanism.
- Deriving current authorization from ledger JSON: rejected; retain an explicit
  locked state row and use the ledger as immutable audit evidence.
- Public signup, automatic grant conversion or a second staff identity: outside
  the approved scope and contrary to independent workflow authority.
