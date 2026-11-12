# Repayment terms captured with the JBL visit

The user approved revealing manual repayment inputs when the LAF is complete,
requiring them before forwarding, and retaining explicit Head of Rural correction.
The current form controls, details/summary, inline validation, media selection,
field-only drafts and revision-checked workflow writes are reused. No design
migration, new capability, browser activation or schema change is introduced.

## Behavior and evidence

Repayment day and Period (months) sit immediately below media, outside the media
disclosure. They appear for a complete selected PDF/image, two named captures,
or successfully stored LAF evidence. Partial captures keep them hidden. Removal
hides but retains typed draft values. Negative outcomes disable these inputs and
preserve canonical terms. Forwarding requires day 1-31 and whole months 1-120;
validation occurs before Drive writes and again at the locked transition.

Head of Rural sees a read-only summary with Edit repayment terms. Closed edits
omit repayment keys; open edits save through the existing final decision, with
before/after terms in its audit event. Recovery retains edit mode and values;
older final drafts with changed values reopen the correction control.

Real signed synthetic Portal testing used local Django/PostgreSQL and the actual
services. Only Drive transport and publication were disabled/replaced. HTTP,
workflow, LAF preparation, case-linked storage and canonical readback ran normally.
The current local artifacts in test-results/visit-repayment-review/ include:

- visit-repayment-mobile.png: LAF and repayment entry below media at 390px.
- final-review-summary-mobile.png: review summary with correction collapsed.
- final-review-correction-mobile.png: explicit correction with entered values.
- result.json: saved terms, workflow state and provider-call readback assertions.

The signed check verifies successful forwarding with 15/12, missing-term client
validation, LAF removal/reselection, stored LAF reuse, final save without changes,
and completing an older case through correction (20/18). No page JavaScript
errors were reported. Browser-only regression checks cover light/dark layouts
from 320px to 1280px, complete/partial LAF readiness, hidden-value retention,
closed-editor omission and correction draft restoration: 17 checks passed.

## Automated validation limits

126 focused Django tests passed before three further boundary tests were added;
all 15 repayment tests passed with the added audit rollback, office-intake caller
and unauthorized final-correction checks. Tests cover missing/fractional/bounded
values, stale revisions, receipts, field-only drafts, negative outcomes,
canonical/text fields, existing Sheet projection and before/after audit.

A wider 193-test Portal run had four pre-existing mismatches: three county-label
capitalization expectations and an IMAB error-code expectation. A wider approval
run also exposed an unrelated delegation error-message expectation; the focused
forward-evidence test passed. The whole browser module has an existing rejected
case summary/fixture mismatch; the 17 repayment/layout checks pass. These broader
suites are not claimed green. No production Google or Telegram writes, physical
camera test, OCR, historical backfill or deployment were performed.
