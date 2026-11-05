# Legacy continuation: selection only

User direction: remove Evidence and explanation because the case notices already
retain the source information. Continuation should require selecting the option.

## Source and behaviour

- `portal_legacy.js` renders only the continuation dropdown, existing confirm
  button and inline feedback. Its duplicated Legacy review summary and explanation
  textarea are removed from both case details and queue drawers. Case Notices
  retain the historical source information; drawers retain Open Case History.
- An empty selection is rejected before sending a request. Selecting an option
  clears that validation feedback. No note is sent by the current UI.
- `portal_legacy/services.py` accepts confirmation without a note. It records
  the actor, selected continuation and source reference through the existing
  legacy/pipeline events. The generated pipeline reason explicitly describes
  the selection and source sheet/row; it does not invent a staff explanation or
  historical facts. Existing clients can still supply an optional note, and
  earlier comments/audit records are unchanged.
- Role, case scope, revision, supported-stage and decision consistency checks
  remain. The same request key replays once; changed facts under that key are
  rejected. No new model or migration is introduced.
- The [automatic refresh and read-only retry](2026-11-05-portal-legacy-continuation-refresh.md)
  remain: successful confirmation updates the case, and a failed follow-up read
  can be retried without confirming twice. The shared script cache version is
  bumped. Existing compact controls and feedback styles are reused.

## Browser evidence

Playwright exercised actual Django pages with signed Telegram authentication,
dedicated local PostgreSQL and synthetic imported cases, with external traffic
denied. Desktop case details and the mobile queue drawer saved a continuation
without any explanation field or note payload. An empty selection, interrupted
save, failed post-save read and read-only retry were also checked. Exact replay
succeeded; changed facts with the same key were rejected.

Database readback confirmed one confirmation event, one workflow revision
increment, the selected stage, correct actor and generated source-reference audit
reason for each successful journey. No page script errors occurred.

- [Screenshots and journey results](../../../test-results/continuation-selection-browser/index.html)

No production deployment or live provider write occurred. Approved UI baselines,
candidate tokens and the Phase 6 migration hold remain unchanged.
