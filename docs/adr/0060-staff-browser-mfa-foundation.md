# ADR 0060: staged company-controlled browser authentication

## Context

The user selected Django accounts plus django-allauth MFA (authenticator TOTP
and recovery codes), rather than an external managed identity provider, for a
browser-convenience pilot with a possible Telegram exit later. Existing Django
workflow grants remain authoritative. Production release/migration state is
unknown. The user separately confirmed browser MFA first and preservation of
existing Telegram signed-launch access.

## Decision

Implement a bounded `staff_auth` integration, beginning with a dormant P1a
foundation. Use the existing Django user, django-allauth 65.20.0 with its MFA
extra, and the library's maintained TOTP/recovery implementation. Pinning a
current compatible release incorporates MFA/rate-limit fixes absent from the
older 64.2.1 example. Django alone supplies no equivalent maintained MFA flow;
custom TOTP/password handling and a second MFA framework are unnecessary.

The foundation adds no operational browser endpoint or publicly mounted
allauth URL. Browser admission defaults off. Telegram authentication, Admin
login, business grants, signing rules and workflow services are unchanged.
Remove vendor credential/email model editors from Admin autodiscovery; generic
JSON editing, deletion and bulk email verification are not an approved
provisioning or recovery interface.
Password-only, Telegram-issued, Admin or client-asserted MFA state must not
qualify for a future company-browser API.

Use allauth's encryption hooks with dedicated, externally managed Fernet keys
for MFA secret material, independent of Django's session-signing secret.
Reject unencrypted/unreadable material; do not fall back to cleartext. Disable
public signup and trusted-browser MFA skipping. Support TOTP/recovery codes
only. Preserve Django's existing password hashers/validators; Argon2 is a
separate optional dependency decision, not an implicit upgrade here.

Register the third-party account/MFA schema through allauth's checked-in vendor
migrations, not duplicated models in legacy core. No new project-owned model
is required in this foundation. Vendor table identity remains package-owned;
document it explicitly instead of renaming its migration schema.

## Consequences

Self-managed credentials require supported staff provisioning, secure password
setup, mandatory enrollment, recovery, audit, session revocation and monitoring.
Those operational flows and UI acceptance must be completed before browser
activation. No email address is assumed verified merely because it exists on a
Django user. Existing email-less/Telegram-only accounts must not gain password
credentials or verified addresses automatically.

Stored Authenticator TOTP secrets and recovery seeds are encrypted through the
adapter. This does not encrypt the entire Django session database: the vendor
pending-enrollment secret is normally session-backed. Secure that transient
storage, centralize the rate-limit/replay cache for multi-worker use, and
implement audited factor-reset/session invalidation before enabling enrollment.

Apply migrations only through the explicitly authorized release process.
Normal rollback keeps the browser flag off and retains additive vendor tables.
Removing vendor schema is destructive: before any MFA enrollment and only
after checking the actual migration plan, the exact schema reversal commands
are `python manage.py migrate mfa zero` followed by
`python manage.py migrate account zero`; these delete vendor credential/email
metadata, not Django users. Once evidence exists, preserve it and use an
approved forward repair instead. No production command is run by this change.

Every phase/merge/deployment handoff includes the change-specific checklist in
`codebase-analysis-docs/assets/PLATFORM_INDEPENDENCE_RELEASE_CHECKLIST.md`.

## Alternatives considered

- Managed company OIDC: the earlier preference, superseded by the user's
  explicit self-managed Django/allauth choice; remains a future provider option.
- django-two-factor-auth: viable, but a second framework is unnecessary given
  the selected allauth TOTP/recovery integration.
- Custom MFA/JWT/browser credential storage: adds security and recovery risk
  without a requirement; do not implement.
- Immediate MFA cutover for Telegram: explicitly deferred to preserve staff use.

## References

- https://docs.allauth.org/en/latest/release-notes/recent.html
- https://docs.allauth.org/en/latest/mfa/adapter.html
- https://docs.allauth.org/en/latest/mfa/configuration.html
