# Origination bootstrap and selected-product deletion

## Context

Origination is being exercised through the normal verified-signing journey.
Deployment currently mistakes setup warnings for security errors, and catalogue
removal retains published test products as tombstones. Blank, reviewed LAFs need
to be available after deployment without repeatedly recreating deleted drafts.

## Decision

Provider configuration, not logging/release labels, determines OTP availability.
Missing setup is a deployment warning; authentication and consent-integrity
errors still block. Runtime signing remains fail-closed.

An opt-in release-stage bootstrap seeds the eleven hash-pinned blank PDFs from
private application assets, using the existing seed contracts without product
assignment or publication. A durable leased operation and compliance completion
record bind the source/contract fingerprint. Completed fingerprints are never
automatically recreated; explicit force is required. No startup hook or cron is
introduced.

An active Superuser may permanently delete explicitly selected global products
and their Origination application/signing rows behind the existing purge gate.
The selection is atomic, idempotent and independently audited. Other workflows
are blockers; shared documents, customer identities and external files survive.
The existing tombstone removal remains a distinct action.

## Consequences

Deleted Origination history is not recoverable through the app. Compliance
evidence survives, and external files require separately authorized cleanup.
Blank PDF assets are private, reviewed and hash-allowlisted. Bootstrap failures
are visible warnings and resumable; drafts still require human alignment and
publication. Normal consent, OTP verification and independent approval rules
are unchanged.

Deployment copies remove author/XMP metadata and retain identical form pages;
original paper hashes and sanitized bundle hashes are tracked separately.
Queued Origination dispatches whose source was deleted complete as cancelled
without contacting a provider. Already-started external calls cannot be recalled.

## Alternatives considered

Simulator-only signing would not exercise the normal journey. Re-seeding on
startup would undo deliberate deletion. Cascading global deletion would destroy
unrelated workflow history. These alternatives are rejected.
