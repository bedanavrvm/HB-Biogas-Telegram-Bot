# Complaints staff browser release

27 October 2026; [ADR 0075](../adr/0075-complaints-browser-production-activation.md).
Implementation is authorized. Production deployment, schema application and
live admission remain pending explicit release approval. This release supports
Complaints only; Portal, Origination and TAT retain their existing channels.
The [verification record](staff-browser-release-checks-2026-10-27.md) records
passed browser/security checks and existing repository-wide release blockers.
Resolve those gates before production activation; never bypass the artifact audit.

## Release configuration

Build the exact reviewed commit with `./build.sh`. It installs the locked browser
development/build dependencies, checks Node 22, types, ADS lint and dependencies,
then produces `browser/dist-production`. Render must use Node **22.23.3**; the
root `.node-version` pins it. Remove an incompatible `NODE_VERSION` override.
Runtime serves the artifact through Django; no separate frontend host is needed.
Do not copy a local demo, test URLconf or `dist-complaints-demo` into production.

Keep both browser flags false for the first code/schema deployment. Review the
normal migration plan, database backup attribution and existing application
release checks; run the existing approved `./release.sh` pre-deploy command.
The only new migration is `staff_auth.0005_browser_setup_purpose`: an additive
purpose column and constraint on expiring setup grants. Existing grants retain
their original first-password meaning. It changes no password, workflow grant,
customer record or signed document.

After the approved code/schema deployment, commission these environment values
through Render's secret store, then rebuild/restart the reviewed release:

| Setting | Required value |
| --- | --- |
| `APP_BASE_URL` | Exact existing HTTPS origin, with no path/query |
| `CSRF_TRUSTED_ORIGINS` | Include that HTTPS origin |
| `STAFF_BROWSER_AUTH_ENABLED` | `True` |
| `STAFF_BROWSER_COMPLAINTS_ENABLED` | `True` |
| `STAFF_BROWSER_DEMO_ENABLED` | `False` |
| `STAFF_BROWSER_INVITATIONS_ENABLED` | `True` |
| `STAFF_BROWSER_EMAIL_FROM` | Reviewed sender on the verified Resend domain |
| `RESEND_API_KEY` | Existing approved Resend secret; never place in source/chat |
| `STAFF_MFA_ENCRYPTION_KEYS` | Dedicated Fernet key ring; retain old keys on rotation |
| `STAFF_BROWSER_SESSION_AGE_SECONDS` | `28800` default; maximum `86400` |

Use PostgreSQL. Settings select the checked-in PostgreSQL native security cache;
do not substitute a local cache, disable native limits or clear live replay rows.
Keep HTTPS-only session/CSRF cookies, the closed account/MFA adapters, mandatory
email verification and TOTP/recovery configuration. `python manage.py check`
and `python manage.py check_production_readiness` must pass for the enabled
configuration. E006 now reports concrete artifact/origin/delivery/store failures;
do not silence it. Build assets, source hashes and lock binding must agree.

Scheduled report delivery retains its own enable flag and approved recipients.
Enabling invitations does not enable scheduled reports or change report scope.

## First account: bedan

The user selected the existing Django Superadmin **bedan** for the first check.
Use that account's existing password and canonical staff email. Do not send a
password, QR secret or recovery code to an agent, log or screenshot.

1. In Django Admin, open **Users → Staff browser access → Manage staff browser
   access**, or `/admin/staff_auth/staffbrowseradmission/manage/`.
2. Select `bedan`, choose **Allow browser access**, enter the administrative
   reason, review the exact account/action, then confirm. This uses the existing
   audited lifecycle and does not alter Telegram or workflow permissions.
3. If the canonical email is not natively verified, choose **Send setup
   invitation** for `bedan`, review the recipient and confirm. The provider's
   acceptance message is not evidence of inbox delivery. If already verified,
   go directly to sign-in; the setup service deliberately rejects replacement
   of an already verified native address.
4. Open the addressed link in a **private browser window**. Django Admin and
   company browser access use separate authentication contexts; an existing
   Admin cookie is preserved and the browser UI asks for a separate session.
   The one-hour link verifies the exact canonical email. It never resets an
   existing password or logs the user in.
5. Sign in with the existing username/password, scan the local authenticator QR
   (or enter its manual key), confirm a current code, and save the recovery codes
   privately. Complete the explicit fresh password/MFA sign-in.
6. Open `https://jbl-biogas-telegram-bot.onrender.com/staff/`. Confirm the correct
   Complaint workspaces and records, detail/reload/Back behavior and sign-out.
   Do not create test complaints in a production group without separate approval.
7. Check email receipt, audit events, secure cookies and current authorization
   against the actual deployed release. Record the operator and result before
   admitting other staff. `bedan` is the first operator; confirm ongoing support
   ownership and identity-verification procedure before wider onboarding.

## Staff onboarding and recovery

Use exact existing staff accounts and current Complaint workflow grants. Browser
admission supplies no business role. Accounts with an existing password retain
it; an admitted non-Admin account with an unusable password may set its first
password after mailbox proof. Initial setup never creates accounts or resets
usable credentials. Canonical emails must be valid and uniquely owned; conflicting
or multiple native addresses require the existing verified support procedure.

Invitation retries retain the same reviewed confirmation and provider key.
An ambiguous response can be retried within the review's ten-minute validity;
after expiry, prepare a fresh reviewed invitation (the old grant is invalidated).
Do not blindly generate multiple invitations. A suspended, expired, changed-email
or changed-password grant cannot be sent or used. Proof bytes remain encrypted
in Django and travel only in the addressed URL fragment, consumed from the URL
by the frontend; the request body is not logged.

The Superuser control also provides **Suspend browser access**, **Sign out
browser sessions**, and **Reset MFA after identity verification**. Reset requires
a non-secret verification reference and recorded reason. It removes existing
factors through the audited lifecycle and invalidates browser generations; it
does not change Telegram, passwords or owning-workflow grants. Never expose the
vendor MFA/email editors or manually clear replay tables as a recovery action.

## Verification and rollback

Local acceptance uses synthetic identities, dedicated PostgreSQL and loopback
Playwright, with provider sends mocked and all external sockets blocked. Run:

```powershell
$env:RUN_STAFF_BROWSER_E2E='1'
$env:STAFF_BROWSER_TEST_NODE='<absolute Node 22 executable>'
$env:TEST_DATABASE_URL='postgresql://<local-test-user>@127.0.0.1:<isolated-port>/<local-test-db>'
.venv/Scripts/python.exe manage.py test staff_auth.tests_production staff_auth.tests_production_transport staff_auth.tests_security_cache --settings=staff_auth.acceptance_test_settings --keepdb --noinput
```

This profile creates/reuses `test_browser_acceptance`; never point it at a
production database or run another flush-based test runner concurrently on it.
Evidence and remaining environment/device gates are in the
[release checklist](../../codebase-analysis-docs/assets/PLATFORM_INDEPENDENCE_RELEASE_CHECKLIST.md).

Monitor browser authentication/setup failures, revocations, correlation IDs,
Complaint authorization/409 conflicts, publication recovery and existing Telegram
requests. Never log credentials, invitation fragments, customer search bodies,
QR data or recovery codes. Confirm images/PDFs and physical-device behavior
before wider use; automated screenshots do not certify accessibility or delivery.

Rollback first sets `STAFF_BROWSER_COMPLAINTS_ENABLED=False` and
`STAFF_BROWSER_AUTH_ENABLED=False`, then restores the previous code/artifact.
Keep the additive schema, accounts, evidence, live replay claims and audit history.
Telegram remains independently authorized. If schema reversal is specifically
required, stop all browser workers and confirm **no `verify_email` purpose rows
exist** before `python manage.py migrate staff_auth 0004_staffbrowsersecuritystate`.
Otherwise keep 0005: dropping its purpose would reinterpret those grants under
old first-password semantics. Never delete evidence to make reversal possible.

Implementation references: [Render Node version](https://render.com/docs/node-version),
[Resend idempotency](https://resend.com/docs/dashboard/emails/idempotency-keys),
[ADS Form usage](https://atlassian.design/components/form/usage).
