# ADR 0067: closed React password/MFA session integration

## Context

The user accepted the P1c.4 composition and instructed proceeding with the
platform-independence plan. The next P1c prerequisite is the real React to
CSRF/session to Django/allauth boundary. The existing preview simulates success
and must not collect credentials. Production browser access remains disabled,
E006 blocking and authentication/business routes unmounted; M0/M1 are unaccepted.

## Decision

Implement P1c.5 as a separately built, dormant authentication entry and a
same-origin, fixed-path, cookie/CSRF transport for the existing session, password,
TOTP/recovery login and logout handlers. Keep the accepted synthetic preview and
its zero-connect CSP unchanged. Authentication state comes from a fresh session
read, never hashes, query parameters, storage, optimistic navigation or client
workflow lists. Refresh masked CSRF from session before each mutation and after
login rotation. Never automatically replay credentials after CSRF/network failure.
Reconcile uncertain responses with a read; remove authenticated content while
rechecking or unavailable. Clear entered secrets after submissions and navigation;
do not persist or log proof, add analytics or accept alternate API origins.

Reuse the documented ADS form, feedback, grid and navigation patterns with the
existing exact graph. Initial setup/enrollment/factor maintenance and workflow
screens remain separate increments: show an explicit support handoff and logout
for states beyond this slice. Identity success alone exposes no business tools.
The user's usability instruction requires short routine sign-in, automatic
session resume, inline recovery, username retention on errors and autofill.
Expired/revoked browser-owned cookies must allow a new password/MFA attempt
without a separate manual logout. Clear only a stale context owned by that exact
cookie user; ordinary Admin/other-channel sessions remain protected. This is a
session restart, never a grant, proof or admission bypass.
Keep the authenticator/recovery switch and cancel action before the field so blur
validation cannot move them during pointer activation. Routine checks are automatic; a
background read must not swallow an explicit logout. A manual recheck is only
needed after an uncertain response.

Exercise the built React entry through Django LiveServerTestCase, real middleware,
database sessions, password and native allauth MFA, using isolated synthetic data
only. The harness URLconf and its asset/context probes are test-only and refuse
non-test settings. No force_login or mocked successful authentication substitutes
for the end-to-end path. Include workflow denial without grants, CSRF rotation,
revocation/expiry, interrupted requests, stale responses, refresh and Telegram
absence. Production settings/URLs/readiness checks, policies and migrations stay
unchanged. No new external dependency or real provider side effect is required.

## Consequences

This proves a bounded local integration, not M1, production static/CSP/cache
delivery, shared native rate-cache readiness, proof delivery or staff admission.
The auth build is excluded from the synthetic preview server and root Telegram
asset pipeline. Rollback removes the dormant entry/transport/test slice and stops
test processes; preserve identities, sessions, factors, audit and workflow data.
No schema or migration reversal applies. Use the existing plan/decision/release
checklist for executed evidence and remaining gates.

## Alternatives considered

- Connect editable fields to the fixed-value preview: confuses simulated and
  real transport and weakens its data-free review boundary.
- Mount production handlers or weaken E006 for a demo: unnecessary before M1.
- Local storage bearer tokens, cross-origin auth or a second backend: unnecessary
  alongside the selected Django session/CSRF boundary.
- Automatically retry password/MFA after an uncertain response: risks duplicated
  credential use; session reconciliation can determine the next permitted step.

References: https://atlassian.design/components/form/usage ;
https://atlassian.design/components/section-message/usage ;
https://docs.djangoproject.com/en/5.2/howto/csrf/ ;
https://docs.djangoproject.com/en/5.2/topics/testing/tools/#liveservertestcase .
