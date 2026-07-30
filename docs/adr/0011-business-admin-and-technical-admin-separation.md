# ADR 0011: Separate Business Administrator from Django technical administration

**Status:** Accepted for code merge and local/staging validation; production migration requires separate deployment approval

## Context

The role code `ADMIN` was used for Portal, TAT, and SPIN authority while
Django `is_superuser` also bypassed all Mini App authorization. This conflated
technical maintenance access with approval, payment, and workflow authority.
It prevented an auditor from distinguishing an operational decision-maker
from a person who can maintain the Django service.

## Decision

- `BUSINESS_ADMIN` is the business-workflow role for Portal, TAT, and SPIN.
  It is granted only through scoped `AccessGrant` or audited emergency access.
- Django `is_staff` and `is_superuser` retain Django Admin/technical meaning
  only. They grant no Mini App role and no Mini App capability by themselves.
- TAT configuration approval requires both the relevant approved capability
  and an explicit TAT `BUSINESS_ADMIN` grant. The requester cannot review
  their own proposal.
- Existing effective grant, emergency-grant, role-capability, and sign-off
  policy rows are renamed by migration 0088. Historic approval/audit rows
  retain `ADMIN` as the original evidence label.
- Before release, the read-only command
  `python manage.py check_business_admin_cutover --strict` must pass. It
  blocks pending legacy policy requests and duplicate effective grant scopes.

## Consequences

Technical Django administrators need an operational grant before opening or
acting in a Mini App. Existing operational authority is retained under the
new role code, and Business Admin access remains workflow/branch/product/group
scoped.

## Alternatives considered

- **Keep `ADMIN` as a workflow role:** rejected because it remains ambiguous
  beside Django administration.
- **Use Django `is_superuser` as Business Admin:** rejected because it grants
  broad technical access and cannot express operational scope.
- **Grant all Django superusers read-only Mini App access:** rejected because
  sensitive customer/financial data requires an explicit business grant even
  for viewing.

## Rollback

Migration `core.0088_business_admin_role_cutover` has not been authorised for
production application by this ADR. Before an approved migration, export
current access-policy evidence and run the strict cutover preflight.

To undo immediately after an approved migration, run:

```powershell
python manage.py migrate core 0087_repair_tat_stage_target_snapshot_backfill
```

The reverse migration restores effective role codes only and stops on an
ambiguous legacy-role collision. It never rewrites historic audit or approval
evidence. Roll back the corresponding application code in the same release.
