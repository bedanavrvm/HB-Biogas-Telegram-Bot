# Closed existing-staff initial setup — P1b.2b.3

Current P1c.6 addendum (20 October 2026): ADR 0068 and browser decision section 12
connect the native contracts to guided first-password/QR enrollment/one-time
recovery screens in the closed React build. Setup/session resumes only exact
verified bound progress; enrollment/session reads a fresh same-channel draft
without seed generation or code redisclosure. Native QR stays local/transient.
Production remains disabled/unmounted; actual delivery/support and M0/M1 remain
open. The sections below retain their original backend scope and test counts.


20 October 2026. Starts at `3d2ffdfb` on Platform-Interdependence. Production
release/migrations remain unknown. This increment adds a dormant backend, not
operational provisioning or delivery. Browser remains disabled, E006 blocking
and production company-login/setup/business URLs unmounted. No commit, merge,
deployment, real staff preparation/password mutation or external mail occurs.

## 1. Scope and identity ownership

The exact existing active Django account and its explicit active browser
admission are required. Initial setup accepts only non-Admin accounts whose
password is still unusable and which have no MFA factors. Django `is_staff`
and `is_superuser`, usable passwords, conflicting canonical/native addresses,
inactive/suspended/deleted identities and ambiguous native address collections
are excluded. Existing credentials require separate verified support/recovery;
this is not a reset API or email-based account lookup.

The operator selects a numeric existing user ID; no new email input or automatic
name/phone/email identity merge is supported. Preparation uses the account's
current canonical email. The same normalized address cannot belong to another
User or native EmailAddress, even if its native row is unverified. Existing
workflow grants, roles, staff flags and Telegram bindings are never altered.

`prepare_staff_browser_setup --actor <id> --user <id>` is preview-only. Apply
requires the exact preview admission revision, snapshot fingerprint, stable
request key and nonsecret reason. Only the currently active Django Superuser can
apply; actor status is rechecked under locks. The account/admission/address
snapshot prevents applying a stale preview. Same-key replay returns the saved
receipt without regenerating proof or changing current state.

Preparation creates/reuses only the sole matching unverified native primary
EmailAddress, increments the browser admission generation and atomically records
an expiring setup grant plus compliance receipt. It never marks an address
verified, sets a password or creates/sends/prints a setup link. Operator results
contain opaque references/fingerprints, not email, proof, password or ciphertext.

## 2. Proof, session and native credential boundary

The one-hour grant contains a dedicated-key encrypted proof. The proof wraps a
native EmailConfirmationHMAC key in a purpose-separated Django-signed envelope
bound to the unique grant. Native keys can repeat for one address in one second;
the envelope prevents a superseded preparation's proof from satisfying a newer
grant. Native confirmation remains the mailbox verifier; no custom TOTP,
password hash, email code or identity provider is introduced.

Relative declarations in `staff_auth/browser_urls.py`, mounted only by tests:

| Handler | Contract | Authority/result |
|---|---|---|
| `GET v1/setup/session/` | Anonymous session and CSRF bootstrap | No staff information or login; existing authenticated cookies receive 409 |
| `POST v1/setup/verify-email/` | `setup_id`, UUID `request_key`, `confirmation_key` | Current exact encrypted/signed/native proof; audited mailbox verification and session-bound password-setup state |
| `POST v1/setup/password/` | `setup_id`, UUID `request_key`, `password1`, `password2` | Same verified anonymous session; native first-password validation/save and atomic completion receipt |

All POSTs enforce CSRF and reject explicit Telegram/app-token/Authorization
credentials through the existing separate browser wrapper. JSON is bounded and
allowlisted. Persistent IP/identity throttles apply. State, user activity,
admission generation, address/password snapshots, expiry and exact durable audit
receipts are rechecked; data submitted by the client never supplies authority.

Verification claims one anonymous session/request key. Exact same-session retry
returns its receipt; another session or key cannot claim the verified operation.
Native verification is called without login-on-verification and cannot establish
a Django login. The prepared native address is already primary and native
CHANGE_EMAIL remains false, so existing canonical User.email is not rewritten.

Only the verified setup session invokes native SetPasswordForm. Native password
validators and adapter set the first password; the completion receipt and proof
erasure commit together. No extra new-password verifier is stored. Exact
same-key retries check the submitted password with Django's existing encoded
password and return the receipt; changed payload/key cannot replace it.
Preparation, verification and completion each have their own idempotent audit.

Setup returns `reauthentication_required`, never `authenticated`. It creates no
MFA assurance or business session. A normal fresh username/password login still
leads to the existing restricted MFA enrollment flow, followed by explicit
logout and fresh password/MFA authentication. Password-only setup is never a
workflow grant.

Native email-confirmed callbacks are synchronous. The endpoint holds if native
notification/email-change settings or new credential-signal receivers introduce
unreviewed side effects, or if the required account adapter is replaced. Native
password-set notification/signal work is deferred until commit; under current
disabled notifications and absent receivers it dispatches no mail. Commit is
not evidence of notification/callback delivery. Review any future change before
removing a hold.

## 3. Failure, interruption and session consequences

Native verification/password changes roll back if their compliance receipt
cannot commit. Browser setup context and queued native success messages are
discarded after audit failure. Session cleanup is explicitly saved on 5xx when
the session store is healthy; an unavailable session store cannot promise
persisted cleanup. No failure grants login or MFA assurance. Wrong proof and
invalid passwords receive safe 400; stale/revoked/cross-session state receives
409; throttling 429; handled crypto/native-setting/audit/credential-store failures
503. These are application-handler outcomes, not an infrastructure uptime claim.

An exact verification retry can restore setup context after a rolled-back
password attempt while the same original anonymous session/proof/request remains
valid. Lost cookies, expired grants, stale account state or uncertain delivery
need a reviewed new preparation/support decision. There is no automatic resend,
proof export or existing-password reset. Completed proof ciphertext is erased.

Setting the initial Django password changes that account's session-auth hash.
Existing Django cookies, including the Telegram session bridge, can expire.
Signed Telegram launch identity and workflow grants remain unchanged; a fresh
valid signed launch can re-establish its bridge. Do not describe this credential
mutation as browser-only revocation or force password/MFA into Telegram.

Expiry/session loss after verification can leave a verified address with an
unusable password. Ordinary preparation deliberately excludes already verified
addresses; a separate reviewed resume/support path is required before use.
Never delete or downgrade a verified address to make preparation succeed.

## 4. Persistence, deletion, migration and rollback

`StaffBrowserSetupGrant` lives in the bounded `staff_auth` app with table
`staff_auth_browser_setup_grant`, catalogue metadata and PostgreSQL table/column
comments. Its expiry index supports bounded retention cleanup. There is one
intentional PROTECT relationship to retained browser admission. Native address
and audit IDs are scalar receipt references, not credential-deletion cascades.
No plaintext email, native key, new password or session cookie is retained here.

Governed hard user deletion still removes native credentials and detaches the
admission. Retained setup state immediately becomes unusable because every
request checks the current linked user/address. The setup grant supplies no
authority after deletion; immutable compliance evidence remains independent.

Migration: `staff_auth.0003_staffbrowsersetupgrant`, additive and no backfill.
Normal rollback keeps all setup routes closed and preserves the table, accepted
native addresses/passwords and audit. Exact destructive pre-use reversal:

```text
python manage.py migrate staff_auth 0002_stafftotpreplaystate
```

This removes only setup-grant state and must never run while a worker can consume
setup. It does not undo accepted email verification/passwords or delete earlier
admission/TOTP replay state. Real credential recovery is separate and verified.
Use actual release authority, backup and worker/schema compatibility evidence
before any production migration; none is performed here.

`purge_staff_browser_setups` previews up to 1,000 expired rows. `--apply` rechecks
expiry during bounded deletion; `--batch-size` permits 1–10,000. It retains live
grants, native addresses/passwords, users/admissions and audit. No scheduler or
real cleanup is run. Assign retention/support ownership before admission.

## 5. Delivery and operational gates

**No mail dispatch or operator proof export exists in this increment.** Synthetic
tests decrypt their own temporary proof to exercise the native backend. That is
not evidence of real mailbox delivery. A later reviewed transport must deliver
only to the still-matching canonical address, protect the proof from logs/URLs,
handle retry/uncertain acceptance durably and retain safe delivery evidence.
Do not manually mark an address verified or send a secret through operator logs.

Real mail/support, interrupted setup, usable-password address verification and
recovery, offboarding/reactivation acceptance, shared native rate-limit cache and
code-key/log privacy, PostgreSQL races, browser/Telegram devices, D13/frontend
acceptance and M0/M1 remain open. No app pilot begins here; Complaints remains
first, followed by separately accepted TAT, Origination and Portal.

## 6. Verification and limits

Final combined run: **187 tests, 178 passed and nine PostgreSQL-only skips**.
This includes all **28 new SQLite tests**, three new setup races and the six
existing lifecycle/enrollment/TOTP replay race skips. The suite is:

```text
python manage.py test staff_auth core.tests_telegram_authentication core.tests_user_identity core.tests_user_hard_delete --keepdb --noinput --verbosity 0
```

Execution used an ignored synthetic-settings/network-denial harness with a
dedicated local SQLite test file under `test-results/` and `--keepdb` to avoid
rebuilding the full migration history on every rerun. No operational database or
`.env` was used. The expanded run used a process-only fast test password hasher;
no committed security setting changed. **Two decisive native setup/password
validation tests also passed separately using the configured password hasher.**
These overlap the combined suite and are not added to its count. Current logs:
`test-results/staff-browser-initial-setup-final.txt`,
`staff-browser-initial-setup-native.txt` and
`staff-browser-initial-setup-governance.txt` (ignored local diagnostics).

The first focused 27-test diagnostic had two failed fixture assertions and two
PostgreSQL skips: Django normalizes an email domain at account creation, and
its lazy user must be accessed before session-hash validation runs. Assertions
now compare the actual original address and explicitly evaluate Django's user.
No runtime policy was relaxed. The final combined pass above includes these
corrections, additional receipt/login-boundary/race cases, and a legacy
case/whitespace duplicate-address check. The earlier diagnostic is not acceptance.

Other passes: all **44 governance/tool tests**; Ruff **0.16.5** over `staff_auth`;
Python compilation; Django system check; no model/migration drift; graph
(**290 migrations, 19 leaves**); model governance; generated/verified catalogue
(**215 application tables**); architecture boundaries; **202-route** write
inventory; UI source ratchet; **28-package** dependency parity and `pip check`;
changed/untracked secret-pattern and diff whitespace checks. The isolated
temporary SQLite migration forward/reversal retained prior admission/replay data
and `auth_user`. SQLite comment warnings and expected denial logs are not
PostgreSQL or real-device evidence.

Wider checks remain non-green: **119** pre-existing environment-template omissions,
**17** prior tracked-artifact allowlist hash mismatches, and the dependency-audit
exception `PYSEC-2026-3412` expired on 2026-09-30. No baseline, allowlist or
exception was changed. Local PostgreSQL tooling is unavailable. Full CI, real
PostgreSQL/worker races, actual mail delivery, devices/staging, support, frontend
licence/build acceptance and production remain unverified.

Tests cover
read-only preview, exact-account preparation/retries, stale actor/snapshot and
ownership denial, native mailbox verification/first-password login boundary,
password validation, rollback, session binding, proof expiry/reissue, account
deletion, shared session-hash changes, CSRF/credentials, native callback holds
and expiry cleanup. PostgreSQL-only preparation/claim races must not be claimed
from SQLite. Full CI, live mail, real users/devices, production and M1 remain
unverified; prior wider environment/artifact/dependency-audit gates are not waived.

## 7. Change-specific handoff checklist

- [x] Existing-account initial-setup service/preview command, three unmounted
  CSRF handlers, temporary security-state model/migration, cleanup, tests,
  catalogue metadata, ADR 0065 and documentation provided.
- [x] No new dependency/env variable/frontend/global cache/business grant,
  production route, account creation, real email, credential export or staff action.
- [x] Record scoped tests, actual skips/failures, governance and isolated schema
  reversal/compatibility evidence. Do not substitute local subset results for CI.
- [ ] Before merge, review native proof binding, replay/state/session rules,
  signal/notification holds and real shared-session consequences. Confirm
  branch auto-deploy behavior before requesting merge/release authority.
- [ ] Before any mail/client activation, accept the real transport, safe secret
  handling, recovery/support owners, PostgreSQL, shared-cache/privacy and remaining
  P1c/M0/M1 gates. No generic allauth endpoints are an alternate setup path.
- [ ] Before deployment, inspect actual release/migrations, backup, worker
  overlap and rollback. Keep browser false, E006 blocking and routes unmounted.
- [ ] After an authorized shared-auth deploy, verify Telegram signed launch,
  scoped read/write and ordinary Admin login. No setup traffic is expected while
  unmounted; investigate unexpected exposure or credential/audit inconsistencies.
- [ ] Monitor duplicate setup claim/completion, incorrect actor/address, missing
  audit, logged proof/password, reset of an existing credential, unexpected mail
  or premature permissions. Use safe request/receipt IDs, never secret material.
- [ ] Rollback preserves accepted native credentials and immutable audit. It
  never restores an old password, clears live grants, deletes users or restores
  the database as ordinary feature rollback.

### STATE BLOCK

- INDEX_VERSION: staff-browser-initial-setup-1 / P1b.2b.3 / 20 October 2026.
- FILE_MAP_SUMMARY: initial_setup.py; setup_api.py; browser_urls.py; setup model,
  metadata/admin/migration 0003; session protection; prepare/purge commands;
  tests_initial_setup.py; ADR 0065; plan/checklist/catalogue/glossary.
- OPEN_QUESTIONS: operational mail delivery, support/recovery, existing usable
  credentials, shared cache/log privacy, PostgreSQL, deployed baseline, owners,
  frontend/D13 and M1. No operational admission authorized.
- KNOWN_RISKS: proof transport or session loss, native callback/configuration
  changes, shared session-hash effects, unsafe rollback/cleanup, unexecuted races
  and premature route/permission activation.
- NEXT_READ_QUEUE: controlled delivery/support or remaining native cache/privacy
  prerequisite; frontend review/P1c; M1 before Complaints; retain M3 investment review.
- VERIFICATION: final 187 tests (178 passed, nine PostgreSQL-only skips), two
  overlapping configured-hasher journeys, 44 governance/tool tests, narrow Ruff,
  relevant static/catalogue checks and isolated additive/reversal rehearsal
  passed. Existing wider 119/17/expired-audit findings remain. No production,
  mail, full-CI, PostgreSQL or operational readiness claim.
