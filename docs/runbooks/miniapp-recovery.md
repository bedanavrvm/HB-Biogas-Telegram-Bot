# Mini App recovery

Each app has **Settings → App status**. Origination has its own header gear;
its signing-delivery warning can open the same panel without leaving the saved
application. Complaints keeps Settings available to authorized staff, while
email administration remains IT-only.

The shared panel uses the existing fonts and controls, keeps ten entries per
page in a contained list, and retains the underlying form/search/filter state.
Every entry has an explicit state and help with a copyable support reference.
Queued/Waiting/Retrying never means a provider update completed.

## Supported recovery

| Owner | Saved work | Action or next step |
| --- | --- | --- |
| Portal | Current case Sheet publication | Confirm Retry sync; current revision and complete Portal grant are rechecked. |
| Portal | Order workbook, retained signed scan | Retry saving the existing bytes through its owner endpoint. |
| Portal | Source upload storage | Retry its existing eligible Drive operation; exhausted/missing source work gives a specific administrator handoff. It never imports rows again. |
| Portal | Already-deleted invoice's unused Drive PDF | Select one cleanup entry and confirm Retry cleanup. Shared/payment evidence remains protected. |
| Portal | Historical payment-document storage | Review the retained payment/document with IT. No repair creates or approves another payment. |
| TAT | Current Sheet dispatch or saved remark | Scoped TAT IT can confirm Retry sync. Signature/notification retry authority is unchanged. |
| TAT | Target Sheet mirror | Group-wide TAT IT only; branch/product-only grants cannot retry a whole-group mirror. App targets remain live. |
| Complaints | Failed register projection | Retry the current complaint snapshot. A leased request receipt prevents duplicate provider attempts/events on transport retries. |
| Origination | Approved document bundle storage | Retry saving the existing approved bundle. Approval, document hashes and signatures remain unchanged. |
| Origination | Signing delivery configuration | Exact deployment-setting handoff; no blind signature or OTP resend. |
| Portal/TAT/Complaints | Latest scheduled email delivery | Check the existing delivery; never Send now as recovery. Uncertain/blocked sends require IT/provider-history review. |

Current permissions determine visibility and available actions. Support steps
do not grant authority. Known configuration/column/identity failures need
repair before another provider attempt. No Mini App edits credentials.
One-off report exports retain their existing owner/status dialog; this panel's
email projection covers scheduled deliveries only.

Successful current work disappears from the list; retained audit/failure records
are not deleted. Portal's bell preserves the same actionable Sheet retry as
Home. System readiness now explains how to repair missing templates and offers
Check app status instead of an unexplained Retry needed label.

## Release and rollback

Ship normal code/static assets and core migration
`0205_tat_publication_retry_capability`. It provisions only the approved TAT IT
Sheet capability and increments the access policy version when it changes a
default. Existing policy decisions are preserved. No manual staff seed command,
new environment variable, new persistent model or provider call is required.
Production deployment/migration needs operator approval.

Rollback follows [ADR 0052](../adr/0052-miniapp-recovery-controls.md). Keep audit
and external-operation evidence. Never clear queues, recreate payments or
regenerate signed bundles as a rollback technique.

## Human acceptance

1. On mobile and desktop, open each app's Settings; confirm refresh/close align
   right and the list scrolls internally with ten entries per page.
2. On Portal Home/bell, confirm Retry sync stays visible. Cancel its dialog:
   no request should be queued. Confirm it: a pending update must not say synced.
3. Revoke/narrow the relevant grant after opening the panel. A stale retry must
   be rejected; refreshing must remove its action/record as appropriate.
4. Retry a failed TAT Sheet update as scoped IT. Confirm the case revision,
   completed stages, scoring and signature counts do not change. Try a signature
   dispatch with that route: it must be rejected.
5. Open Settings from a saved/unsaved form, then close it. Search, filters and
   entered values must remain. Neither closing nor refreshing resubmits a form.
6. For Drive failures with retained bytes, confirm saving retries only those
   bytes. Verify actual Google/Telegram/Resend results in the approved staging
   environment; synthetic local checks do not establish live provider health.
