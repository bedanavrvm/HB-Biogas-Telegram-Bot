# Staff Lifecycle Workspace

## Purpose

The Staff Lifecycle workspace is the normal administration surface for
permanent Mini App access and ordinary staff account status. It keeps
authorization (`AccessGrant`) separate from operational routing
(`TatResponsibilityAssignment`) while allowing one durable plan to update both
atomically. An active Django Superuser applies a plan directly by default or
may deliberately request an independent checker decision.

Open **Django Admin > Configuration > Users > Staff lifecycle workspace**.

For the one-time BotFather and Render setup required by Telegram identity
activation, see [Telegram Staff Activation Mini App Setup](telegram-staff-activation-setup.md).

## Authority and approvals

No checker is required for **Apply now**. Direct onboarding requires the active
Superuser to review the server-derived summary while using their authenticated,
CSRF-protected Django Admin session; it does not request a second password.
Direct changes to existing staff and pending non-onboarding plans retain current
Django Admin password confirmation.

To use **Send for independent review**, appoint an active non-Superuser Django
staff account as an Access Control Checker. When no checker exists, the root
Superuser may appoint the first checker from that user's page by:

1. entering an audit reason;
2. typing `APPOINT FIRST CHECKER`; and
3. submitting the appointment.

This bootstrap appoints a reviewer only. It does not grant Mini App access.
Optional plans appear under **Configuration > Staff approvals (N)**. The maker,
target, and proposed replacement cannot independently approve that plan.

## Standard workflow

1. Choose onboarding, access change, transfer, leave, return, or offboarding.
2. Select the target staff member. Superuser accounts are intentionally absent.
3. For onboarding, enter the login channel and identity details.
4. Select existing grants to retire and add the required replacement scopes.
5. Choose a replacement when the target owns TAT responsibilities.
6. For leave, choose the return time and only the approval gates that must be delegated.
7. Enter a specific business reason.
8. Choose one decision path:
   - **Review and apply now**: review the exact summary, re-enter the current
     Superuser password, then confirm. The change applies immediately.
   - **Send for independent review**: an eligible checker opens
     **Staff approvals**, reviews the before/after state and impact, and approves
     or rejects it.

Either decision path applies the complete plan in one database transaction. A
stale policy version, changed grant, changed responsibility, or
completed/rerouted task stops the plan without applying a partial result.
Double-submission with the same request key and same details returns the
original result. The same key cannot be reused for changed details.

## Journeys

### Onboarding

Direct onboarding creates the account shell and applies activation, initial
access, and routing atomically after Superuser confirmation. Optional review
creates an inactive account shell; it becomes effective only after checker
approval.

For Django Admin onboarding, re-enter the new staff member's initial password
after the direct preview. Password inputs are intentionally never rendered back
by the server. Raw passwords are not stored in plan snapshots or audit records.

For Telegram staff, explicitly select the Telegram groups the person is meant
to join. The server verifies that every group is compatible with the final
AccessGrants; broad workflow access never silently invites a person to every
configured group.

After direct application, the plan page shows a copyable activation pack once.
Give its Mini App link and eight-digit code only to the intended person. The
code expires after 15 minutes, is single-use, and is blocked after five failed
attempts. The card provides a one-tap copy action and a live countdown based on
the server-issued expiry time. Signed Telegram identity, enrolled username, and
the code must all agree. Use **Generate replacement activation pack** if it
expires.

After verification, the system:

1. refreshes the existing shared launcher in each selected group;
2. creates a one-member invite link expiring after 24 hours;
3. privately welcomes the staff member with authorized Mini App buttons and
   the group invitations; and
4. records group joins without repeating the public welcome.

When the invited staff member joins a governed group, the bot publishes a
fresh copy of that group's shared **JBL Apps** launcher and pins the new
message. This makes the Mini App button available even when Telegram hides
messages sent before the person joined. Repeated Telegram join updates do not
publish another copy, and a launcher-delivery failure does not undo the
verified group join.

Telegram does not allow the bot to force-add a person to a group. The staff
member must accept each invitation. Unknown or manually added members retain
the existing public group welcome. A delivery failure does not roll back the
active account or grants; the plan page shows **Attention required** and an
active Superuser can use **Retry Telegram delivery**.

### Transfer and access change

Use **Change role or scope** for permanent authority changes. Use **Transfer**
when access and TAT ownership move together. Existing grants remain unless
they are explicitly selected for retirement.

### Temporary leave and return

Leave retains permanent access but moves affected TAT ownership and creates
selected approval delegations for up to 14 days. It may start immediately or
be approved for a future time. A replacement must already hold matching
access. A staff member covering another leave cannot themselves be placed on
leave until that dependent coverage is resolved.

Run `python manage.py process_staff_lifecycle_plans` from the production worker
schedule at least once per minute. A future plan is revalidated when it becomes
due and becomes stale instead of applying if authority or routing has changed.

Use **Return** to restore the recorded pre-leave primary routing and revoke the
delegations created by that leave plan. If routing changed independently while
the employee was away, return is blocked for manual reconciliation.

### Immediate offboarding

Offboarding takes effect after the selected direct or independent decision.
Before submission, provide replacements for every active TAT responsibility.
Application deactivates the account and retires permanent grants, emergency
grants, delegations, checker authority, and pending access requests. Open TAT
work is rerouted with its existing task-generation lock.

### Emergency access

Emergency access remains the separate four-hour mechanism for temporary
access. An active Superuser may issue one narrowly scoped grant with a
mandatory reason. Approvers are notified, the event is permanently audited,
and the grant cannot change permanent access or TAT ownership. It is not
needed for direct permanent staff lifecycle changes.

## Existing pending plans

An active Superuser may open an existing pending plan and either:

- enter a decision reason and current password to **Apply now**; or
- enter a cancellation reason and current password to **Cancel plan**.

An eligible checker may still approve or reject a pending plan that remains in
the independent-review decision mode.

## Conflict recovery

- **Open plan already exists:** directly apply or cancel it from the plan page,
  or leave it for an eligible checker.
- **Plan is stale:** refresh the staff state and create a replacement plan.
- **Replacement is ineligible:** give the replacement matching access through
  a separate governed lifecycle action first.
- **Return routing changed:** reconcile the current TAT roster instead of
  overwriting the newer assignment.
- **Wrong Telegram binding:** submit a governed Telegram identity reset; never
  edit the numeric ID directly.

## Visual acceptance checklist

Use synthetic users only.

- The workspace fills the available Admin content width without squeezing fields.
- Onboarding fields appear only for onboarding; target selection appears for other actions.
- Current grants load for the selected user and can be retired explicitly.
- Submit immediately disables and displays a working state.
- Direct review clearly shows the exact target, final grants, routing/task
  impact, and business reason. Existing-user changes also show current-password
  confirmation; onboarding shows that the active Superuser session is sufficient.
- The plan page clearly separates before, proposed, impact, maker, decision
  mode, and decision actor.
- **Staff approvals (N)** is visible to appointed checkers and opens only
  eligible pending independent-review plans.
- The maker cannot see an enabled checker action on their own optional-review plan.
- A Superuser can password-confirm direct application or cancellation of an
  existing pending plan.
- Success, stale, rejection, and validation messages remain compact and visible.
- Layout remains usable at desktop, tablet, and narrow mobile widths.
- The activation code is shown once and no raw code appears in logs or diagnostics.
- Telegram group choices are explicit and incompatible groups are rejected.
- The plan page shows activation, welcome, launcher, invitation, expiry, and join status.
- The private welcome contains only authorized Mini App launchers.
- Failed Telegram delivery is visibly retryable without recreating the user.

## Maintenance notes

- Production must keep `ACCESS_GRANT_GOVERNANCE_ENFORCED=True`.
- Permanent grants must be changed through governed services; direct ORM writes
  intentionally raise `PermissionDenied`.
- Direct Superuser decisions must use `submit_lifecycle_change`; do not bypass
  the plan, request fingerprint, or compliance ledger.
- Django Superuser lifecycle is a separate god-mode procedure and is not handled here.
- The bot must be an administrator with invite-user and pin-message rights in
  every selected group. Missing rights appear as a retryable onboarding error.
- Configure `STAFF_ACTIVATION_MINI_APP_SHORT_NAME` to the BotFather Mini App
  whose URL is `/api/staff/activate/`; this ensures Telegram supplies signed
  `initData` when the activation pack is opened.
- The complete registration, deployment, verification, and troubleshooting
  procedure is documented in
  [Telegram Staff Activation Mini App Setup](telegram-staff-activation-setup.md).
- Invite URLs are retained only until the private welcome succeeds; durable
  evidence stores their SHA-256 digest and expiry, never the usable secret URL.
