# ADR 0016: Master Data current pipeline state

**Status:** Accepted for code merge and local/staging validation; production
migration application and Apps Script deployment require separate release approval.

## Context

The Master Data register preserves stage-specific history: the JBL visit
outcome, credit decision, final review, order, invoice, and payment data. It
did not provide one reliable answer to the operational question: *where is
this case now?* Staff could misread an old JBL comment such as `Awaiting
Analysis` after a credit decision had already moved the case forward.

The business also requires an unambiguous treatment of halts. Deferral stays
valid for 90 days and then requires reappraisal; it must not look like an
ordinary waiting state. There is no `Approved with Conditions` path in the
current process. Payment finalization is the terminal state for this release.

## Decision

Publish a backend-owned `Current Pipeline State` column to the Master Data
register. Its value is derived from canonical Django state and never accepted
as a Sheet-originated update. Historical stage columns remain unchanged.

The active labels are:

| Situation | Current Pipeline State |
|---|---|
| HBG visit has not yet been received | Awaiting HBG Visit |
| HBG visit received, JBL visit still pending | Awaiting JBL Visit |
| FarmUp handoff before a JBL visit | JBL to Schedule Visit |
| JBL visit rescheduled | JBL Visit Rescheduled |
| JBL visit deferred/on hold | Deferred — JBL Visit |
| JBL visit rejected/cash/other partner | Rejected by JBL / Closed — Opted for Cash / Closed — Other Partner |
| JBL visit approved or awaiting analysis | Awaiting Credit Analysis |
| Credit approved | Awaiting Head of Rural Review |
| Credit/final/order/payment deferred within 90 days | Deferred — Credit / Head of Rural Review / Order / Payment |
| Deferral reached 90 days | Reappraisal Required |
| Final approval before assignment | Ready for Order |
| Assigned order without a matched invoice | Ordered — Awaiting Invoice |
| Matched invoice/payment batch/payment review | Payment Processing |
| Payment document finalized | Payment Finalized |
| Credit/final rejection or withdrawal | A stage-specific rejection label or Withdrawn |

The Master Data Apps Script resolves columns by header name rather than fixed
letters. It must not insert, clear, or move business columns. Its
`Current Pipeline State` column is warning-protected and labelled as
backend-owned, because the Django publisher needs to keep writing it.

## Consequences

Master Data staff get a current-state summary without losing the evidence
needed to explain how a case got there. The derived field takes precedence for
operational scanning; historical comments remain evidence, not current state.

Removing conditional decisions prevents a decision that no downstream rule
supports. The existing approval/audit structures remain readable so no
historical evidence is destroyed.

## Alternatives considered

- **Infer state manually from several columns:** rejected because old values
  remain visible and are easy to misinterpret.
- **Let staff edit one summary column in Sheets:** rejected because Sheets is
  a register, not the workflow authority.
- **Add Approved with Conditions:** rejected because there is no agreed
  conditions-clearance workflow in the current business process.

## Rollback

Migration `core.0094_alter_jawabuapprovalrecord_decision_and_more` changes
choice metadata only; it does not alter case state, financial data, Sheets, or
Drive files. To undo an explicitly approved application:

```powershell
python manage.py migrate core 0093_requisition_publication_retry_key
```

Prefer an application-code rollback for a display issue. Do not deploy the
Apps Script or apply the migration to production without separate approval.
