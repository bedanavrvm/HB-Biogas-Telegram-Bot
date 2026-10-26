# ADR 0068: guided closed browser onboarding

## Context

P1c.5 proves native sign-in locally. The user instructed proceeding and avoiding
further authentication delay. Existing initial-password and enrollment handlers
already own credential validation, audit and admission; the missing piece is a
usable guided client. Production authentication and M0/M1 remain closed.

## Decision

Complete P1c.6 in the existing dormant auth entry. Consume a prepared invitation
from a URL fragment, erase it before rendering/authentication requests and submit proof only
after the user's Continue action. Never accept proof in query strings or create
accounts/grants. Resume verified setup only from its bound server session.

Create the password with native validation, then perform explicit-action native
password login/enrollment begin using that same submitted password, without
retaining it between screens or retrying it automatically. Ordinary unenrolled
login likewise begins enrollment as part of the submitted sign-in action. Native
password recheck remains enforced. Return native allauth QR markup as a bounded
data image, with manual setup key fallback; no QR service or new dependency.

Read-only setup/enrollment progress may return current state to the exact bound
session. It must not generate seeds, repeat code disclosure, grant assurance or
change audit/credentials. Existing locks, expiry, receipts and admission checks
remain authoritative. Recover interrupted confirmation through those reads.

After successful activation, retrieve one-time recovery codes in the same
explicit verification action. Display/copy them only on that transient screen.
Never automatically repeat disclosure. Clear sensitive material on navigation,
hide, cancellation and errors. A lost disclosure gives an honest support path,
not regenerated factors. A single saved-codes action signs out into the existing
fresh password/MFA login required by ADR 0063. Setup itself never grants access.

Reuse the reviewed ADS graph/forms/feedback and document a native credential QR
image exception if required. Test the complete React/native journey using only
isolated synthetic invitations/factors, including denied, interrupted and stale
paths. Mask proof-bearing QR/codes in screenshots and diagnostic output.

## Consequences

The guided client closes the local onboarding UI gap; actual invitation delivery,
support, production static/origin/cache and M0/M1 acceptance remain release work.
Native flash messages are replaced by explicit JSON feedback only on these
requests, including commit callbacks; other requests and notification delivery
keep their normal behavior. No operational mount, new package, schema, migration, policy/grant or Telegram
change. Rollback removes this client/progress/test slice; retain accepted native
credentials, factors and audit evidence. No schema reversal applies.

## Alternatives considered

- A new identity/signup service or extra dependency: duplicates existing native
  contracts and expands scope.
- Repeated manual password/support forms: unnecessary for an explicit submission
  that can invoke the existing native checks sequentially.
- Grant access during setup or replay proof after failure: violates the settled
  assurance and one-time disclosure boundaries.

References: https://atlassian.design/components/form/usage ;
https://atlassian.design/components/section-message/usage ;
https://atlassian.design/components/button/usage ;
https://docs.allauth.org/en/latest/mfa/adapter.html .
