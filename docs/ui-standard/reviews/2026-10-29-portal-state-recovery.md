# Portal state and recovery interactions

29 October 2026. User-authorized Portal follow-up, verified with Playwright
instead of test runners. Existing Telegram shell, buttons, confirmation and
submission sheets, file picker, inline feedback, queues and invoice detail are
reused. No CSS system, token or approved-baseline change.

The [full state matrix](../../portal-state-recovery-review-2026-10-29.md) records
causes, transitions, denied writes and limits. Open the
[local gallery](../../../test-results/portal-state-recovery-review/index.html).

## Sources and intentional behaviour

- `portal_farmer_sheet.js`: expired Revisit guidance names Operations/FarmUp and
  a new JBL visit. Open FarmUp requires its existing commit capability.
- `portal_farmup.js`: retain uncertain save in tab memory; confirm exact payload
  and key before validating further edits. Existing counters distinguish saved,
  selected and held rows. No new persistent browser storage.
- `portal_invoices.js`: existing cancel/withdraw/follow-up/verification and
  preparation actions live on current invoice detail. Superseded invoices link
  to their replacement. User-approved Resolve identity flag requires matching
  IDs, existing manager authority and a note. Submission errors keep the
  note/file and confirmation in the existing sheet.
- `portal_payments.js`: upload visibility follows the server's existing physical
  sign-off policy and document scope. Other staff see the responsible-role handoff.
- `base_shell.html`: cache versions bind those scripts. These are nonvisual and
  existing-component interaction corrections, not candidate-token adoption.

Server authorization, revision checks, source binding, append-only evidence and
financial finality remain mandatory. No new role, schema or route.

## Manual evidence

| Interaction | Gallery artifact |
|---|---|
| Expired case handoff / working FarmUp navigation | `expired-deferral-operations_admin-handoff-after-390.png`; `reappraisal-handoff-and-layout.js.result.json` |
| Server saved, response lost; remaining selection retained | `farmup-partial-response-lost-remaining-retained-390.png`; `lost-response-partial.js.result.json` |
| Expired approvals appear before detail read | `credit-expired-approval-visible-before-detail-after-390.png`, `final-expired-approval-visible-before-detail-after-390.png` |
| Note-required flag resolution / denied and stale requests | `flag-resolution-ui.js.result.json`; flag-resolution captures |
| Inline cancellation / withdrawal / recoverable follow-up | `correction-cancelled-start-followup-available-after-390.png`, `invoice-withdrawn-followup-needs-fresh-identity-390.png` |
| Lost follow-up response / same UUID on retry | `followup-lost-response-recovered-after-390.png` |
| Current replacement handoff | `replacement-current-handoff.js.result.json`; replacement captures |
| Revoked access retains file and confirmation | `agreement-revoked-access-file-retained-after-390.png`; `agreement-grant-revoked-after.js.result.json` |
| Configured policy / restored authorized upload | `payment-policy-operations-handoff-after-390.png`, `payment-upload-revoked-grant-file-retained-390.png`; `payment-policy-ui-after.js.result.json` |
| Five recovered invoice types complete payment | `identity-recovered-five-payment-completed-final-390.png`; `identity-payment-final.json` |
| Existing sheet at narrow/phone/desktop widths | `identity-reverification-sheet-320.png`, `identity-reverification-sheet-390.png`, `identity-reverification-sheet-1280.png` |

The gallery distinguishes earlier/intermediate states. Captures are synthetic
browser evidence, not human design approval, real Telegram, screen-reader
acceptance, provider delivery or deployment. Final source hashes are recorded
in registry changes and the local manifest. Approved/legacy hashes, pending
review status and Phase 6 migration hold remain unchanged.
