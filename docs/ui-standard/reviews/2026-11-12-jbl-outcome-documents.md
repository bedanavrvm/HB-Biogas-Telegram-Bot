# JBL outcome requirements and complete document upload

User approval: Implement the plan; searchable filenames added during execution.
Existing Portal form, native select, details/summary, inline errors, media picker,
SecureMediaViewer, capture slots, camera and pending-state controls are reused.
This is a source-bound interaction change, not Phase 6 design migration.

The outcome and physical-visit selection precede date/location requirements.
Non-forwarding evidence is collapsed and optional. Forwarding opens required
evidence and locks physical visit to Yes. Deposit cards remain identifiable and
can open for outcome-only actions. No new role or browser channel is activated.

## Observed browser evidence

A real local Django Portal shell and PostgreSQL database were used with an
actual signed synthetic JBL officer launch. Outbound hosts were blocked. Drive
transport was replaced with a failure/success stub; all case transitions,
authorization and document preparation used real application code.

Artifacts in test-results/jbl-outcome-review/:

- queue-before.png: ready case before deposit holds.
- outcome-only-desktop.png: rejection without date/location/documents.
- complete-document-preview.png: selected combined PDF preview.
- optional-evidence-pending.png: outcome committed while evidence failed.
- positive-desktop.png: positive requirements and retained files.
- outcome-mobile.png: compact 390px shell; outcome save exercised.
- positive-mobile-fresh.png: fresh 390px positive form; visible save and inline validation exercised.
- accessible-upload-mobile.png: keyboard-operated upload; non-visit fields hidden.
- browser-result.json: successful behavior assertions and canonical DB readback.

Combined PDF and image selection, two-photo order swap, status switching,
negative outcome save, retained files after upload failure, evidence-only retry,
positive required fields and fresh mobile outcome save were exercised. No browser
JavaScript errors occurred. A desktop-to-mobile viewport change in a single
open test dialog retained the original shell height; mobile verification uses a
fresh mobile launch. Physical Android camera hardware and real Drive transport
were not tested.

## Automated checks

44 targeted API/service/form regressions passed before the added naming work.
50 outcome/document/upload/naming/permission checks passed after naming was added.
The broader 273-test run retained 58 failures also present in a detached HEAD
baseline (principally old auth/configuration/audit fixtures and assertions).
There were no additional failing tests compared with that baseline; three
baseline failures were resolved by updated affected fixtures/receipt assertions.
This is not a claim that the wider suite is green.

Operational rules and file-retention limits are documented in
[the runbook](../../runbooks/jbl-visit-outcomes.md).

## Upstream integration

Rebased onto the seventeen missing origin/main commits on 12 November 2026.
Remote legacy/import fixes and both source-review histories are retained.
Combined Portal assets use fresh cache versions and source hashes.
The incoming legacy-previsit test now exercises the forward outcome for its
held-deposit assertion; outcome-only saves remain permitted.

After integration, 95 focused tests passed, including the new upstream FarmUp,
legacy-previsit and Sheet-status checks and the signed Portal credit-label
browser check. The reused loopback PostgreSQL test database was initialized
with its missing audit-chain singleton by a local test runner; application
validation and audit logic were unchanged. UI ratchet and Ruff checks passed.
