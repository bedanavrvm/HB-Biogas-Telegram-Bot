# ADR 0075: Conditional production browser delivery for Complaints

27 October 2026. Implementation authorized by the user's request to finish the
real staff browser release. Deployment remains a separate reviewed action.

## Context

The native password/MFA, admission, PostgreSQL security state and Complaint
operations adapters exist, but production URLs and assets are absent. Initial
setup has no operational invitation sender or Admin handoff. The old unconditional
E006 release block describes a foundation that has since gained those adapters.

## Decision

Serve the integrity-checked native Complaints production build on the existing
same-origin Django deployment under `/staff/`, with fixed asset URLs and the
existing native API contracts. Never import a test URLconf or simulator. Keep
both browser flags default-off; disabled routes return 404 and production checks
validate enabled configuration rather than accepting a blanket bypass.

Retain existing staff identities, audited active-Superuser browser admission,
current Complaint workflow grants, native password/TOTP/recovery, revocation,
CSRF, encrypted factors and PostgreSQL atomic security state. Add a narrow Admin
handoff for these existing lifecycle actions and expiring mailbox invitations.
An existing password is never replaced by initial setup; mailbox-only proof may
verify the exact admitted existing account without logging it in. Invitations
use the existing fixed-endpoint Resend transport, their own enable/sender
configuration and stable provider idempotency keys. Proofs stay encrypted in the
existing setup grant and appear only in the addressed email's URL fragment.

Build with the pinned Node/lock during image preparation; runtime needs only
Django. Verify source/artifact bindings, CSP and included notices. Add scoped
production-route, onboarding, revoked/denied and PostgreSQL/browser acceptance
checks. Document remaining operator/device/deployed-environment evidence honestly.
No other Mini App gains a browser adapter or inherited authority.

## Consequences

Deploying this code alone leaves browser access off. Operators must commission
the reviewed configuration, existing staff admission and mailbox/MFA workflow.
Disabling browser flags is the first rollback step; keep live security rows,
existing accounts, audit evidence and signed/operational workflow data intact.
Schema reversal, if needed, must follow the release record after disabling all
browser workers. Provider acceptance is not proof of inbox delivery.

## Alternatives considered

Mounting test hosts, exposing synthetic credentials, enabling generic allauth
signup, resetting staff passwords automatically or inferring Complaint grants
from browser admission would violate the existing identity/authorization model.
A separate frontend host adds cross-origin session/CSP configuration without
being necessary for this first production workflow.
