# ADR 0012: Root Superuser checker bootstrap

**Status:** Accepted for code merge and local/staging validation; production migration requires separate deployment approval

## Context

Mini App access policy changes already require a maker-checker approval flow,
but the original Django Superuser could not approve any request until someone
had manually placed a user in a Django Group.  This created a bootstrap
deadlock for a sole technical administrator and made the checker designation
an implicit Group-membership side effect rather than auditable authority.

`BUSINESS_ADMIN` remains a scoped operational workflow role.  It must not be
confused with Django Admin, the technical Superuser, or access-policy checker
authority.

## Decision

- An active Django Superuser is a root technical access-policy approver. It
  still receives no Portal, TAT, SPIN, payment, or other Mini App authority
  without an explicit scoped `AccessGrant`.
- A Superuser may appoint or revoke an active `is_staff` user as an
  independent **Access Control Checker**. Appointment and revocation require
  a reason and are written to an immutable compliance-audit event.
- Non-superuser checker authority is stored in `AccessControlCheckerAssignment`,
  not inferred from direct edits to the historical `Access Policy Approvers`
  Django Group. Existing active group members are backfilled as legacy
  checker appointments during migration 0090.
- A requester normally cannot approve their own access-policy request. The
  only exception is a sole active Django Superuser while no different root
  Superuser or appointed checker exists. The bootstrap override requires an
  explicit approval reason and creates a distinct audit event.
- As soon as an independent checker exists, self-approval is denied again.
  Technical Superusers can still manage checker appointments, but standard
  capability, grant, and document-signoff changes remain maker-checker
  controlled.

## Consequences

The initial technical administrator can establish the first reviewer without
an operational deadlock. Subsequent access-policy changes receive an
independent decision trail. Direct Django Group edits cannot silently grant
checker authority after the migration.

Checker users need deliberate Django Admin access (`is_staff=True`) because
the current review interface is Django Admin. That technical login does not
grant Mini App business access.

No Mini App cache stores checker authority. The service resolves checker state
from Django on each access-policy action; applying a standard policy request
continues to increment the existing policy version returned to Mini App
clients.

## Alternatives considered

- **Allow Superusers to self-approve forever:** rejected because it removes
  separation of duties once another reviewer is available.
- **Continue using only a Django Group:** rejected because direct membership
  edits lack appointment/revocation reason and a dedicated immutable audit
  record.
- **Make `BUSINESS_ADMIN` a checker automatically:** rejected because business
  workflow authority and technical access-governance authority have different
  scopes and audit expectations.

## Rollback

Migration `core.0090_accesscontrolcheckerassignment` creates only checker
appointment records and backfills active members of the historical approver
group. Before any approved production rollback, export checker appointment and
compliance-audit evidence.

To undo the schema change:

```powershell
python manage.py migrate core 0089_portalcaseworkspace_portalsavedview
```

This removes the new checker-appointment table only. It does not alter Users,
Access Grants, workflow state, financial records, or the compliance-audit
ledger. Roll back the associated application code in the same release.
