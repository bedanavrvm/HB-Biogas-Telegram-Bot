# Staff Lifecycle Workspace

## Purpose

The Staff Lifecycle workspace is the only normal administration surface for
permanent Mini App access and staff account status. It keeps authorization
(`AccessGrant`) separate from operational routing (`TatResponsibilityAssignment`)
while allowing one independently reviewed plan to update both atomically.

Open **Django Admin > Configuration > Users > Staff lifecycle workspace**.

## Before the first plan

An active, non-Superuser Django staff account must be appointed as the Access
Control Checker. When no checker exists, the sole root Superuser may appoint
the first checker from that user’s page by:

1. entering an audit reason;
2. typing `APPOINT FIRST CHECKER`; and
3. submitting the appointment.

This bootstrap appoints a reviewer only. It cannot grant Mini App access, and
the root Superuser still cannot approve their own lifecycle plan.

## Standard workflow

1. Choose onboarding, access change, transfer, leave, return, or offboarding.
2. Select the target staff member. Superuser accounts are intentionally absent.
3. For onboarding, enter the login channel and identity details.
4. Select existing grants to retire and add the required replacement scopes.
5. Choose a replacement when the target owns TAT responsibilities.
6. For leave, choose the return time and only the approval gates that must be delegated.
7. Enter a specific business reason and submit the plan.
8. A different Access Control Checker opens the plan, reviews its before/after
   state and impact counts, and approves or rejects it.

Approval applies the complete plan in one database transaction. A stale policy
version, changed grant, changed responsibility, or completed/rerouted task
stops the plan without applying a partial result.

## Journeys

### Onboarding

The workspace creates an inactive account shell. The account, initial access,
and routing become effective only after checker approval.

For Telegram staff, approval leaves identity binding pending. Generate the
activation code from the user page and give the eight-digit code only to the
intended person. The code expires after 15 minutes, is single-use, and is
blocked after five failed attempts. Signed Telegram identity, enrolled
username, and the code must all agree.

### Transfer and access change

Use **Change role or scope** for permanent authority changes. Use **Transfer**
when access and TAT ownership move together. Existing grants remain unless
they are explicitly selected for retirement.

### Temporary leave and return

Leave retains permanent access but moves affected TAT ownership and creates
selected approval delegations for up to 14 days. It may start immediately or
be checker-approved for a future time. A replacement must already
hold matching access. A staff member covering another leave cannot themselves
be placed on leave until that dependent coverage is resolved.

Run `python manage.py process_staff_lifecycle_plans` from the production worker
schedule at least once per minute. A future plan is revalidated when it becomes
due and becomes stale instead of applying if authority or routing has changed.

Use **Return** to restore the recorded pre-leave primary routing and revoke the
delegations created by that leave plan. If routing changed independently while
the employee was away, return is blocked for manual reconciliation.

### Immediate offboarding

Offboarding takes effect when the checker approves it. Before submission,
provide replacements for every active TAT responsibility. Approval deactivates
the account and retires permanent grants, emergency grants, delegations,
checker authority, and pending access requests. Open TAT work is rerouted with
its existing task-generation lock.

### Emergency access

Emergency access is the sole deliberate checker bypass. An active Superuser
may issue one narrowly scoped grant for four hours with a mandatory reason.
Approvers are notified, the event is permanently audited, and the grant cannot
change permanent access or TAT ownership.

## Conflict recovery

- **Open plan already exists:** decide, reject, or cancel that plan before creating another.
- **Plan is stale:** refresh the staff state and create a replacement plan.
- **Replacement is ineligible:** give the replacement matching access through a separately approved plan first.
- **Return routing changed:** reconcile the current TAT roster instead of overwriting the newer assignment.
- **Wrong Telegram binding:** submit a checker-approved Telegram identity reset; never edit the numeric ID directly.

## Visual acceptance checklist

Use synthetic users only.

- The workspace fills the available Admin content width without squeezing fields.
- Onboarding fields appear only for onboarding; target selection appears for other actions.
- Current grants load for the selected user and can be retired explicitly.
- Submit immediately disables and displays `Submitting…`.
- The plan page clearly separates before, proposed, impact, maker, and checker.
- The maker cannot see an enabled approval action on their own plan.
- Success, stale, rejection, and validation messages remain compact and visible.
- Layout remains usable at desktop, tablet, and narrow mobile widths.
- The activation code is shown once and no raw code appears in logs or diagnostics.

## Maintenance notes

- Production must keep `ACCESS_GRANT_GOVERNANCE_ENFORCED=True`.
- Permanent grants must be changed through governed services; direct ORM writes
  intentionally raise `PermissionDenied`.
- Do not restore the historical immediate Superuser grant inline.
- Django Superuser lifecycle is a separate god-mode procedure and is not handled here.
