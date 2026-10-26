# ADR 0065: Closed initial setup for an existing admitted staff account

Date: 20 October 2026

## Context

P1b remains disabled and unmounted. Telegram onboarding creates existing Django
users with unusable passwords; ordinary Admin accounts already have usable
credentials. Initial provisioning must not become public signup, email-based
identity linking, an Admin password reset or a source of workflow grants.
Native mailbox verification and password validation must precede MFA enrollment.
Mail transport, frontend and operational support are still unaccepted.

## Decision

Deliver P1b.2b.3 as one dormant initial-setup backend. An active Django Superuser
can preview and explicitly prepare the exact existing, active, browser-admitted
non-Admin account. It must have an unusable password, a valid current canonical
email, no MFA factors and no conflicting User/EmailAddress ownership. No email
argument, name matching, account creation or grant change is supported.

Preparation creates/reuses only that account's sole unverified native primary
EmailAddress. It increments the browser admission generation, invalidating older
setup/login attempts, and creates a one-hour setup grant with an encrypted native
EmailConfirmationHMAC key in a purpose-separated Django-signed envelope bound
to the unique grant. Native keys can repeat for the same address/second; the
envelope prevents that from reusing an older preparation's proof. A payload-bound
compliance receipt commits atomically.
Operator output contains no address, key, setup link, password or ciphertext.
Same-request retry returns the original receipt, never regenerates a proof.

Three relative, unmounted CSRF endpoints provide anonymous setup-session
bootstrap, native mailbox-proof verification and native first-password setting.
The proof must match the encrypted issued key and native confirmation, exact
account/address/password/admission snapshots, expiry and durable preparation
receipt. Verification claims the grant for the current anonymous session and
request key and records an atomic receipt. It never calls login-on-verification.
Other authenticated cookies are rejected without logout or account switching.

Only that verified setup session can invoke native SetPasswordForm. Its native
validators and adapter set the first password; usable-password and privileged
accounts cannot enter this path. The password mutation, completion receipt and
proof erasure commit together. Same-key completion retries use native password
checking against the current encoded password; no extra password digest or
plaintext is retained. Setup creates no Django login, MFA assurance, staff flag,
Telegram binding or workflow authority. Explicit normal password login and MFA
enrollment/login follow. No generic allauth URLs are mounted.

Use the native form without the headed authenticated-session finalizer: this
flow is anonymous and must not preserve or issue an authenticated session.
Native password-set notification/signal work is scheduled after successful
commit. Hold setup when native email-change/notification settings or new
credential-signal receivers would introduce unreviewed side effects. No callback
delivery or operational notification behavior is certified by database commit.

The new bounded `StaffBrowserSetupGrant` retains only admission ownership,
native address ID, keyed fingerprints, encrypted temporary proof, state,
session/request bindings, receipt IDs and dates. There is deliberately no FK to
the native address or User: governed hard deletion retains admission but removes
native credentials; every setup request rechecks the live owner/address. Expired
grants can be removed by bounded preview-first cleanup without removing native
addresses, passwords or audit. No live credential editor is exposed in Admin.

There is **no dispatch/export of the proof** in this increment. A later reviewed
mail worker must deliver only to the still-matching canonical address; operator
receipt/authorization is not proof of mailbox ownership. Synthetic tests read
their own encrypted native proof. No real email, staff preparation or password
change is performed while implementing/testing this slice. UI and transport are
not implied by the closed endpoint declarations.

## Consequences

Setting the first Django password changes Django's session-auth hash. Existing
Django sessions for that exact account can expire, including the Telegram session
bridge. Signed Telegram launch identity and grants are unchanged; a fresh signed
launch can re-establish its session. Do not promise browser-only revocation for
an actual password mutation. Existing usable Admin/staff passwords are excluded.

Current global browser-off/E006/unmounted protections remain. Mail delivery,
interrupted-setup support, usable-password address verification/recovery, shared
native cache/log privacy, PostgreSQL, frontend and M1 remain separate gates.
Unknown production release/migrations are not inferred from local tests.

Migration `staff_auth.0003_staffbrowsersetupgrant` is additive, no backfill.
Normal application rollback preserves grants, native addresses/passwords and
audit, keeping all setup routes closed. Exact destructive pre-use reversal:
`python manage.py migrate staff_auth 0002_stafftotpreplaystate`. Never reverse or
clear live setup grants while a worker can process setup. Reversal does not undo
accepted passwords or verification, which require separate verified recovery.

## Alternatives considered

- Public signup or account lookup by email: risks duplicate/merged identities.
- Operator sets or prints an initial password/proof: unnecessary credential
  disclosure and does not establish mailbox ownership.
- Mark canonical email verified during preparation: an administrative choice is
  not mailbox proof.
- Generic password-reset/factor-management routes: expand scope and can alter
  existing Admin/shared credentials.
- Immediately send mail or mount a browser shell: transport/support/frontend
  acceptance is not yet available; no delivery is authorized by this backend.

## References

- ADRs 0060–0064; `staff_auth/lifecycle.py` and `enrollment.py`.
- Pinned allauth 65.20.0 `EmailConfirmationHMAC`, email-verification flow,
  `SetPasswordForm` and password-change flow.
