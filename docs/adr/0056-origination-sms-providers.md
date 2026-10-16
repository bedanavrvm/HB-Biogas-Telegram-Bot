# Origination SMS providers and delivery evidence

## Context

Origination uses Africa's Talking for invitations, locally generated OTPs and
withdrawal notices. Advanta is an optional alternative, not a signing engine.
The user chose environment selection for new links only, retaining each link's
original provider. Advanta publishes no submission idempotency contract or
authenticated callback contract.

## Decision

One Origination-owned SMS module implements both providers. Existing sessions
are statically classified as Africa's Talking; new sessions capture
`ORIGINATION_SMS_PROVIDER` (default `africas_talking`). Each message uses its
session's provider. Credentials stay in the deployment secret store.

Reuse IntegrationOperation for single-attempt submissions and redacted delivery
evidence. Never automatically retry an uncertain submission or fail over.
Explicit OTP resend creates a new challenge under the existing shared limits.
Read-only Advanta delivery lookups use separate fenced leases and a bounded
schedule; they never reopen submission operations or advance signing.

## Consequences

Keep both providers configured while their links remain usable. Account
fingerprints prevent lookup against a different provider account. Old receipt
IDs are always namespaced by provider and ambiguous matches are ignored.
OTP verification does not depend on a delivery receipt. No OTP plaintext,
signing tokens, SMS bodies or credentials enter operation metadata. Roles,
consent, document bytes and approval rules are unchanged.
Sentry frame-local collection is explicitly disabled platform-wide: transport
locals can contain API credentials and OTP text even when exception messages
and request bodies are scrubbed. This enforces the existing privacy policy;
it changes neither workflow permissions nor error grouping.

## Alternatives considered

Global immediate switching would unexpectedly reroute existing links.
Automatic failover risks duplicate codes/messages. Unauthenticated callbacks
cannot supply trustworthy Advanta delivery evidence; authenticated polling is
the supported first release. No new queue framework or billing subsystem is
needed.

## Rollback

Normal rollback selects `africas_talking` and restarts the deployment; existing
Advanta links still require their credentials until expiry/replacement. Retain
the additive schema and delivery history. For schema reversal, first stop new
Advanta links, drain/expire them and export delivery evidence; then run
`python manage.py migrate origination 0008_unsigned_application_completion`
and `python manage.py migrate core 0205_tat_publication_retry_capability`.
Older code cannot interpret Advanta sessions, so do not run it against active
Advanta links. Production deployment/migration needs separate authorization.
