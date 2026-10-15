# Portal confirmations and direct IT settings

## Action inventory

The Portal action modules, generated forms and template inputs were checked.
Reuse `PortalDialogs.confirmAction` for a routine action requiring consent, not
new business information. Cancel, Escape and backdrop clicks make no request.

| Action | Interaction |
| --- | --- |
| Remove an unsigned payment case | Confirmation; the server supplies an action description and retains actor/time/revision/history. |
| Ignore, restore, unmatch or delete invoices | Existing confirmations, now using the shared dialog. Deletion protections remain. |
| Match when the applicant already has an invoice | Confirmation instead of a mandatory reason-only form. |
| Flag invoice identity for review | Confirmation. The hold remains; this is not an identity approval. |
| Cancel an unsent name-change request | Confirmation; invoice and history remain. |
| Withdraw a sent request | Explicit confirmation that HB was notified. No fabricated email/reference and no identity-hold bypass. |
| Start a follow-up | Confirmation; identity must be checked again. |
| Confirm corrected invoice, same phone | Confirmation without an optional empty note field. |
| Confirm corrected invoice, different phone | Keep the required verification note and preserve it after failure. |
| Confirm same/different invoice holder | Keep identity evidence; different national IDs cannot be declared the same person. |
| Correct parsed invoice or case facts | Keep the actual fields and correction context. |
| Credit/final/payment decisions | Keep the decision and relevant comments/conditions. These are business decisions, not confirmation-only actions. |
| Relationship, signed agreement or media | Keep the relationship inputs, conditional explanation and upload controls. |
| Number lookup, sequence adjustment, pause notice, delegation | Keep the actual number, pause explanation or coverage details. These supply information the action cannot infer. |

Read ADR 0053 before adding another action-note prompt. No external notification
is sent just because staff confirm that they notified HB.

## Product labels and payment readiness

SysUp's saved `payment_product` label is sufficient for the payment workbook.
An unresolved global catalogue binding is neither a picker warning nor a reason
to disable selection. The same readiness function drives the picker and add
validation. It still requires the accepted signed order, invoice/identity facts,
customer number, payment values, repayment details and applicable approval.
Requirements of an explicitly selected product version still apply. Product-
scoped grants are not inferred from arbitrary free text.

## Settings

Authorized TAT IT saves targets, calendar and escalation rules directly using
the existing change/audit records. New saves do not wait for a second actor.
The frontend receives `approved` and says Saved. It hides the reason-only field.
Earlier pending changes remain available to apply/discard after confirmation;
they do not silently override a newer save. Replays are bound to actor, group,
setting and values. Inactive users and grants from another Mini App cannot save.

Personal preferences, Portal settings and report delivery settings already save
directly. This change does not alter access-control reviews, financial approval,
signed-document finality or Origination signing authority.

## Verification and rollout

- Browser fixtures exercise the real Portal shell/styles at 320, 390, 430 and
  1280px, light/dark confirmations, focus/keyboard cancellation, duplicate-click
  exclusion, payment removal and corrected-invoice note preservation.
- Django tests exercise saved SysUp text through readiness, picker and actual
  batch membership; direct settings, replays, cross-workflow denial and history.
- Deploy code/static assets normally. There is no schema or permission migration
  and no provider configuration change. Existing requests/history are retained.
- Local validation uses SQLite/Python 3.14. Production Python 3.12/PostgreSQL,
  live Telegram rendering and real provider writes remain unverified.
- Results: 149 payment/invoice checks and 35 TAT settings/target checks passed.
  Two pre-existing payment-document failures remain documented in
  `KNOWN_GAPS.md`. All 15 browser checks, first-party JavaScript syntax, Django
  configuration and migration-drift checks passed.
- Code rollback restores the earlier UI/settings-save behavior. Retain the
  completed configuration audit rows and invoice/payment history; rollback
  does not turn already applied settings back into pending proposals.
