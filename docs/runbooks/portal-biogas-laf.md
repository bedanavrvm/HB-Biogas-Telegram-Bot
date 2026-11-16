# Optional Portal Biogas LAF

Implementation date: 16/11/2026. Production enablement is a separate release action.

## Staff flow

Upload/camera is primary. **Fill Biogas LAF** is secondary and opens only the
published, product-compatible Lipa Mdogo Mdogo Biogas Main LAF. Save and resume
from the same case. Opening a draft does not change the active upload source.

Complete missing fields and preview each page. The assigned BRO signs their
configured slot; a separately configured second BRO must be another authorized
officer. A configured client/guarantor signs personally on the officer's device
and confirms consent. The authenticated officer confirms witnessing that person's
signature. No OTP, SMS provider or separate client account is required.
There are no remote invitations.

Select **Use this filled LAF** once its visit signatures are complete. Existing
uploads remain retained. The analyst and Head of Rural sign at their existing
credit and final-review stages. Signatures do not themselves record the business
decision; use the existing stage action after signing. Negative outcomes retain
their existing requirements and do not demand approval signatures.

Confirmed signatures lock answers and source bytes. A correction uses **Replace
LAF**, retains previous versions/signatures and requires fresh signatures. Return
the case to its visit stage through the existing controlled rework process first
when a later-stage case needs replacement. Source changes/replacements invalidate
affected Portal approvals. No historical uploads are converted automatically.

## Configuration and deployment

1. Review `docs/adr/0084-portal-biogas-laf.md` and the source-bound UI review.
2. Back up PostgreSQL and apply the checked-in `portal_lafs` migrations through
   the normal approved deployment. No production migration is authorized merely
   by these instructions.
3. Verify exactly one active product-compatible `lipa_mdogo_mdogo_laf` Main LAF,
   published field alignment and every required signature/date/stamp placement.
   Existing document configuration remains authoritative. No seed rerun is needed.
4. Check the Portal BRO, credit and Head of Rural grants independently of
   Origination. Grant changes remain under their existing governance.
5. If client/guarantor slots are configured, review their placed signature fields
   and test consent plus officer-witness confirmation on the officer's device.
6. Enable `PORTAL_LAF_FORM_ENABLED=True` only after the local tests and the
   deployment's actual Biogas form/placements have been reviewed. Default is False.

New drafts use the published snapshot. Saving an unsigned draft adopts a
compatible newly published alignment/version and retains the previous answers
in its superseded draft. Review the updated form before signing. Any confirmed
signature prevents automatic document adoption.

## Persistence, archive and recovery

Saved drafts, frozen PDF bytes and signature evidence live in PostgreSQL. They
remain available if Drive is down. Completion reserves a durable
`portal_laf_archive` integration operation; a bounded wake-up thread assists it.
Opening a completed case wakes retained due work after a process restart.
For explicit manual recovery, `python manage.py drain_portal_lafs --apply`
processes at most ten
operations per pass and uses the integration operation's leases/retry schedule.
Without `--apply`, the command only inspects retained operations and makes no Drive calls.
The in-app **Retry archive** action retries publication only. A failure never
replays the business decision or signature. Names contain the client name/ID,
document type and version UUID, within the existing controlled Drive hierarchy.

Turning the feature flag off prevents new case adoption. Existing LAF cases keep
their controls and evidence checks so disabling a flag cannot bypass signatures.
Use the reviewed source-switch/rework flow to return a case to uploaded evidence.

Rollback: disable new adoption, export all Portal LAF tables and retained PDF
bytes, then `python manage.py migrate portal_lafs zero`. This removes the new
tables; do not run it before evidence export. Original upload and Origination
records are not removed. Restore the matching code/configuration release.

## Removing a test case

With `MINIAPP_TEST_DELETION_ENABLED=True`, an active Superuser can select the
test case in Admin → Jawabu farmer masters and choose **Delete selected test
records**. Review the impact before confirming. Draft and signed digital LAFs,
all superseded versions, signatures and request receipts belong to that case
and are included. Selecting LAF evidence also includes its owning case; it
cannot remove a signature from a surviving case.

Unrelated cases and shared LAF templates survive. Linked order/payment workspaces
appear in the impact preview; keep test cases in separate batches. Finance
numbers remain consumed. Independent compliance evidence and Drive files are
retained; exact Sheet-row cleanup is queued and retriable. Pending LAF archive
work is cancelled. An archive already running finishes before deletion can
proceed; a changed receipt requires a fresh impact confirmation.

This is selected-record test cleanup, not a group-wide Portal reset. The setting
defaults off; no deletion is authorized by deployment alone.

## Verification boundary

Local tests and browser review use synthetic cases and blocked external sockets.
They do not establish production template readiness, live
Drive archival or authorization to activate the feature in production.
