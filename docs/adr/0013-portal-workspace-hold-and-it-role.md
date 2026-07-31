# ADR 0013: Pause private Portal workspace for scoped IT support

**Status:** Accepted for code merge and local/staging validation; production migration requires separate deployment approval

## Context

Portal private workspace features—saved views, pins, recently opened cases,
and automatic case-open tracking—were introduced as user-owned convenience
data. Operational rollout is now paused. The data must remain intact for a
future approved rollout, but it must no longer be visible or writable by
ordinary Portal staff.

The platform also needs one clear technical-support role in every
access-controlled Mini App workflow. Django technical flags are deliberately
not a substitute for that scoped operational identity.

## Decision

- Keep `PortalCaseWorkspace` and `PortalSavedView` data and the related
  service code. Do not delete or purge workspace records as part of this hold.
- Add the reviewed `portal.workspace.manage` capability. It depends on
  `portal.case.read` and is initially allowed only for Portal role `IT`.
- Enforce the capability at every workspace API endpoint and before recording
  an automatic case-open event. The Portal UI never loads or renders workspace
  controls for an actor without that capability.
- Add `IT` as a controlled, explicitly grantable role in Portal, Complaint
  Cases, TAT Tracker, and SPIN. The initial seed provides only minimal
  read/support capabilities; it does not grant unrelated business writes.
- The migration respects pre-existing explicit allow/deny policy rows. When it
  adds default rows it increments the access-policy version, snapshots the
  policy, and records a system-originated hash-chain audit event so active
  Mini Apps refresh their authorisation state.

## Consequences

Operational staff retain their normal queues and personal display settings but
no longer see or access private saved views, pins, or recents. An appointed
IT user must still receive an `AccessGrant` for the specific workflow and
scope; Django `is_staff` and `is_superuser` confer no Mini App privilege.

The hold is intentionally reversible through the existing maker-checker
capability matrix: an approved future request may grant
`portal.workspace.manage` to another controlled role. This preserves a clear
audit trail instead of relying on a code rollback.

## Alternatives considered

- **Delete private workspace models and data:** rejected because it destroys
  user-owned records and makes an approved later rollout need a new migration.
- **Hide only the UI:** rejected because stale clients or direct requests
  could continue accessing data.
- **Use Django Superuser/`is_staff` as the IT override:** rejected because
  technical-admin flags and Mini App workflow access must remain separate.

## Rollback

Migration `core.0091_pause_portal_workspace_to_it` is data-only and its
reverse intentionally preserves the policy rows, snapshot, and audit evidence.
It never changes cases, financial records, Sheets/Drive, or private workspace
rows.

Do **not** roll back Portal application code to re-open workspace access.
To end the hold, create a reasoned access-control capability request for
`portal.workspace.manage`; the normal independent-checker rule applies, with
only the separately documented sole-root bootstrap exception available.
