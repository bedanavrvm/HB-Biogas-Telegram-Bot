# Portal Revisit detail and legacy changeover

31 October 2026. Retains the user's compact Portal art direction and existing
cards, buttons, forms, feedback, navigation and permission boundaries.

Revisit details now show the rejection/deferral stage, reason and explanation
separately, with recorded time where available. Case History uses the same
server-owned decision context. Missing history is labelled rather than invented.
The map uses Lucide pin, refresh, zoom, external-link and popup-close icons with
existing compact controls and accessible names; Leaflet attribution is retained.

All Cases adds a scoped, collapsible legacy preview/commit workspace. Source-row
identity and durable per-row checkpoints support 50-row saves and explicit
reconciliation. Feedback and controls remain visible while reviewing rows;
failed reconciliation inputs are retained. Legacy source facts/notes and missing
fields appear in Case History. Stage and HB handover confirmations use current
Operations/IT scope and an audit explanation. HB commissioning distinguishes
unknown historical status/date from a pending or completed event.

Source provenance and historical exceptions are operational data changes, not
new UI tokens, a replacement shell, ADS adoption or approval of a full redesign.
Source ratchet changes retain original hashes and the Phase 6 migration hold.

## Evidence

Local synthetic artifacts are in `test-results/portal-legacy-review/`, including
the actual browser/API observations and an evidence gallery. Playwright uses the
real Django shell and PostgreSQL state; synthetic tile/Sheet transports are
identified separately. Initial failures were inspected and corrected rather
than hidden behind assertions. No test runner or synthetic pass/fail suite was
used. Evidence establishes the captured interactions, not human design approval,
physical-device accessibility or production operation.

The [changeover runbook](../../runbooks/portal-legacy-changeover.md) documents
workbook handover, grandfathering boundaries, finance references, publication
binding review and the final live cutover gate. The user's real workbook has
not been imported; no production Sheet/Drive/Telegram writes are authorized here.

## Observed results

- 122 synthetic source rows were reconciled in resumable chunks; a duplicate
  identity and invalid amount were held first, then explicitly linked/corrected.
- Concurrent PostgreSQL commits of one row returned one case and one import event.
  Correctly scoped Operations succeeded; another branch/group and Origination-only
  IT were denied. Complete dates retained their exact value.
- A bare Approved remained Legacy review; an explicit matching credit decision
  advanced to final review, while conflicting comments remained unresolved.
- Native commissioning completed with a new supplied date and an unknown old
  installation date. No historical signoff, installation date or actor was created.
- Revisit captures cover 320/390/1280 pixels, stage/reason/explanation, zoom, refresh,
  pin popup/close and unavailable tiles with the external-map recovery link.
  A failed commit request retained selection; saved progress resumed after reload.
- Synthetic Sheet binding preview wrote nothing. Duplicate/stale manifests were
  refused before writes; reviewed application resumed in 50/50/21 chunks and
  queued 121 durable publications after Case ID readback. No real Sheet was used.
- Django system/migration consistency checks and JavaScript syntax checks passed.
  No automated test suite was run. Production import/bindings, real provider
  publication and physical-device acceptance remain pending.

Rehearsal used separate local PostgreSQL database `hb_legacy_review_test` on
loopback 5543. Browser screenshots with geometric map tiles use an intercepted
synthetic tile transport; failure captures deliberately abort tile requests.
The in-progress real workbook was inspected read-only for header/formula
compatibility and was never imported or rewritten.
