# Withdrawn in stage status controls

User direction: remove the standalone Mark Withdrawn section; choose Withdrawn
through each stage's existing status/decision control.

## Source and interaction

`portal_farmer_sheet.js` adds **Withdrawn** to the existing JBL Outcome, Credit
Decision and Final Decision dropdowns for authorized existing cases. It requires
the existing Comment field as the withdrawal reason, hides irrelevant rejection
reason choices and changes the submit label to **Save Status**. Withdrawing does
not require or record a visit, visit documents, an IMAB approval or repayment
terms. Selected unsaved visit attachments must still be saved or removed first.
Normal outcome choices retain their existing validation and submission paths.

Case details place the same transition in the current stage's **Status** field,
inside its existing expandable section. This also supports Order Preparation
and JBL cases whose deposit prevents visit activation. The status control
replaces the current stage's read-only status/decision row rather than adding
another global section. Other stage facts remain visible. New unsaved leads do
not expose withdrawal.

The standalone Mark Withdrawn section is removed. **Resume Case** remains only
for withdrawn cases with a known originating stage and the owning stage's
authority. Choosing Withdrawn uses the existing revision-checked withdrawal API,
required note, audit/comment history and durable publication reservation; stage
decisions and prior evidence are not overwritten. No backend policy, role,
database schema or new status meaning was introduced. Known order, invoice and
fulfilment evidence suppresses the choice; the server independently retains all
financial/finality guards.

An interrupted write retains its request key. After a confirmed save, a failed
case read offers **Retry loading case**, retrying only that read. This follows
the [legacy continuation refresh](2026-11-05-portal-legacy-continuation-refresh.md)
completed alongside this change. Shared shell cache versions bind both updates.

## Real browser evidence

Playwright used actual Django pages, signed Telegram authentication and dedicated
local PostgreSQL with synthetic cases. It exercised:

- JBL, Credit and Final Review queue forms, plus Order's existing case section.
- Required withdrawal notes and the absence of standalone Mark Withdrawn controls.
- The pending-deposit case's JBL-stage status control without fabricating a visit.
- Read-only retry after an Order withdrawal saved but its follow-up GET failed.
- Same-case resumption at the originating stage for all four stages and the
  pending-deposit case.
- Protected invoice evidence: no status editor and a direct signed withdrawal
  request rejected without changing the case.

Database readback confirmed one withdrawal and one resume event per eligible
case, restored original stages and no created JBL visit for pre-visit cases.
The protected case remained unchanged. No page script errors were recorded.

- [Status dropdown screenshot gallery](../../../test-results/withdrawal-status-browser/index.html)
- [Journey result](../../../test-results/withdrawal-status-browser/result.json)
- [Continuation refresh evidence](../../../test-results/continuation-refresh-browser/index.html)

No production deployment or live external provider write occurred. Approved
visual baselines, candidate tokens and the Phase 6 migration hold are unchanged.
