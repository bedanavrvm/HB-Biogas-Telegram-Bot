# ADR 0019: Django Superuser Access Grant override

**Status:** Accepted for code merge and local/staging validation. Production
release requires separate approval under the repository release process.

## Context

The existing maker-checker path correctly protects capability-matrix,
document-signoff, and standard staff-access requests. In this deployment,
however, only the technical Django Superuser has a configured Django Admin
login. Requiring that account to request an Access Grant and wait for a second
technical checker prevents ordinary staff setup and repair.

`BUSINESS_ADMIN` and `IT` remain scoped operational Mini App roles. Django
technical flags must not grant their holders automatic Mini App authority.

## Decision

- Any active Django `is_superuser=True` user may immediately create, edit,
  activate, deactivate, or delete an `AccessGrant` from the canonical Django
  User administration screen.
- Each operation is applied only through `apply_superuser_grant_override`.
  It creates an applied `AccessControlChangeRequest`, retains before/after
  snapshots, writes immutable compliance-audit evidence, captures a policy
  snapshot, and increments the shared policy version.
- The override is limited to individual staff `AccessGrant` rows. It does not
  grant Mini App access to the Django Superuser itself, and does not bypass
  maker-checker for role-capability matrix, document-signoff policy, or TAT
  configuration changes.
- Standard request/review routes remain available for changes that should
  receive independent approval. No notification is sent merely because a
  Superuser exercised this direct administration path.

## Consequences

The sole technical administrator can enroll staff and correct their workflow
access without an impossible approval loop. The resulting access decision is
still visible in the access-control queue and compliance ledger, including
the explicit `django_superuser_override` decision mode.

Mini Apps receive the new policy version on their next metadata fetch and
therefore re-resolve affected access. Existing server-side authorization
continues to check the current `AccessGrant` rather than trusting a client
session.

## Alternatives considered

- **Keep the sole-root bootstrap exception only:** rejected because it stops
  working as soon as a checker or second root exists, while the operational
  administrator still has no practical way to set up staff access.
- **Make technical Superuser status a Mini App role:** rejected because it
  would collapse technical administration and operational authority.
- **Allow raw inline database writes:** rejected because they would bypass
  policy snapshots, audit evidence, and active-client access refresh.

## Rollback

This change has no schema migration. To undo it, redeploy the prior
application commit. Applied Access Grants and their audit/snapshot evidence
are intentionally retained; do not delete compliance records as part of a
rollback. Review any direct overrides made during the release window through
the Access Control Change Request evidence view.
