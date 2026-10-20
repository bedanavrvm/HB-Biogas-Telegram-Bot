# ADR 0064: Shared one-use TOTP admission for the closed browser adapter

Date: 20 October 2026

## Context

P1b.2b.1 is implemented but browser authentication remains disabled and its
routes unmounted. The next bounded prerequisite is replay protection across
workers. The pinned allauth 65.20.0 validates a TOTP and then calls the default
Django cache's `add()` for one period. The current default is process-local.
The same cache also holds Origination PDF template data, Daraja credentials and
diagnostic suppression state. Changing it is a separate shared-runtime decision.

The approved direction retains native allauth authentication. Reimplementing
TOTP, changing global cache semantics or exposing generic account routes would
expand this increment unnecessarily.

## Decision

Add P1b.2b.2: a database-backed one-use guard to the closed browser adapter's
native headless MFA input. Subclass the pinned native input/view; run native
validation first, then reserve successful TOTP use before native authentication
is saved or browser assurance/audit can be completed. Recovery codes keep their
native consumption behavior. The native headed fixture is not a production
entry point and is not certified by this browser-only guard.

`staff_auth.StaffTOTPReplayState` stores only a purpose-separated HMAC digest
and expiry. Its key includes the native factor identity and canonical validated
code, keyed by that factor's decrypted seed. No seed, code, employee identifier,
IP address or arbitrary serialized cache value is stored in this table. The
factor seed makes the digest stable across Django/encryption-key rotation;
authentication secrets remain encrypted in the existing native factor row.

A unique primary key admits the first use. An expired row is renewed with one
conditional database update, so competing renewals cannot both win. Unexpired
entries must never be evicted or cleared. Retain a claim conservatively for
`MFA_TOTP_PERIOD * (2 * MFA_TOTP_TOLERANCE + 1)` seconds after native acceptance.
This covers the complete remaining native acceptance window without changing
which codes native validation accepts. A new browser login requires a fresh
code; the existing authenticated-session lost-response retry stays idempotent.

Storage/encryption failure denies authentication with a safe 503 and clears the
current browser authentication context. It never falls back to local-cache-only
success. A claim may remain consumed when later login audit/session delivery
fails; staff must use a fresh code. Such a failure is not permission to clear
live replay state.

Provide bounded, preview-first expiry cleanup, deleting only rows still expired
at deletion time. Do not register startup/cron work or touch production data.
The table has no user foreign key and grants no authority. Metadata, comments,
an expiry-index justification and checked-in migration are required.

## Consequences

The global cache, native request/rate-limit implementation, passwords, grants,
Telegram authentication, frontend/dependencies and production routes remain
unchanged. This closes one browser TOTP replay boundary, not the complete P1b
shared-cache/abuse, provisioning/recovery/support or M1 acceptance gates.
Native rate-limit cache sharing and operational cache topology remain open.
PostgreSQL races must be executed before operational acceptance; SQLite tests
cannot certify concurrent workers. Alternate/generic/headed MFA routes must not
be mounted as a way around this adapter.

Migration: `staff_auth.0002_stafftotpreplaystate`, additive with no backfill.
Normal application rollback leaves the browser closed and preserves the table.
Exact destructive reversal before any operational use is
`python manage.py migrate staff_auth 0001_initial`. It removes replay state only;
it needs release authority and must never run while any browser worker can
authenticate. Retain the existing admission and native factor tables. Reopening
after loss of replay state requires all prior code acceptance windows to end
and fresh password/MFA authentication; deployment is not authorized here.

## Alternatives considered

- Redis/Memcached: shared cache is valid future work but adds deployment and
  dependency obligations beyond this bounded local backend increment.
- Django's general database cache: changes other cache consumers and its
  culling/general serialized values are unsuitable as an implicit security
  contract. Its expired-row behavior also needs its own concurrency review.
- Replace native TOTP verification or monkey-patch vendor globals: unnecessary;
  a scoped native input/view subclass preserves the maintained verifier.
- Use only existing HTTP throttles: they limit requests, not successful code
  reuse across independent native cache instances.

## References

- ADRs 0060–0063 and `staff_auth/browser_api.py`.
- Pinned source: `allauth/mfa/totp/internal/auth.py`,
  `allauth/headless/mfa/inputs.py` and `allauth/headless/mfa/views.py`.
- https://docs.allauth.org/en/latest/common/rate_limits.html
- https://docs.djangoproject.com/en/5.2/topics/cache/
