# Portal Withdrawal and Independent Register Review

The user approved a Withdrawn outcome before signed orders, same-case resumption
without deferral reappraisal, consistent display capitalization and a completed
Commissioning tick. The follow-up removes the blocker between Master Data and
Eco-conserve imports being reviewed together.

## Behaviour and source choices

- Mark Withdrawn and Resume Case reuse the compact case-section disclosure,
  existing buttons, inline validation and sticky feedback. They appear in case
  history and the existing stage/Revisit forms, using the current stage's Portal
  write capability. No spacing, typography, navigation or token redesign.
- Withdrawal requires a note and retains its canonical origin stage. Resume
  restores that stage on the same case. Existing visits, approvals and comments
  remain evidence; original intake timing is retained. Withdrawal creates no
  60-day deferral deadline, and its recorded duration is excluded from measured
  TAT. Independent approval validity still applies.
- Revisit includes withdrawn cases. Summary, timeline, filters and existing
  pipeline reports expose the outcome. Unknown historical withdrawal stages
  stay unknown and require source review; no automatic stage backfill.
- Both transitions are revision-checked, request-keyed, audited and reserve the
  existing Sheet publication path. Pre-existing orders must use the unsigned
  order controls first. Invoice/payment/HB fulfilment evidence blocks this action.
  Selected unsaved visit attachments must be saved or removed before transition.
- Names in the case detail use display title case for uniform upper/lowercase
  input, retaining mixed-case spelling and known acronyms. Locations use uppercase.
  Stored biodata, identifiers and staff-written prose are unchanged.
- The Commissioning circle now uses the completed tick when HB commissioning
  is recorded, rather than remaining the current-stage clock. Withdrawal shows
  its originating stage and keeps later stages pending.
- The old importer mutex checked every frozen upload in the group. It now checks
  the same group **and register** under the existing group transaction lock.
  Different registers can be reviewed/imported/projected independently; concurrent
  cutovers for the same register remain blocked. Normal owner writes remain held
  until all active cutovers complete or are safely cancelled. Shared identity
  reconciliation remains required when source rows refer to an existing identity.

## Verification evidence

Actual Django pages, signed Telegram authentication and PostgreSQL were used with
synthetic data. Playwright exercised all four withdrawal/resume stages, required
notes, reload persistence and chronological history, plus desktop/mobile
Commissioning and both resumable register pages. The completed journey reported
no page script errors. Provider traffic was denied; local Sheet boundary fixtures
were used for projection.

- [Withdrawal and parallel-review screenshot gallery](../../../test-results/portal-withdrawal-browser/index.html)
- [Playwright result](../../../test-results/portal-withdrawal-browser/result.json)
- [Historical-report screenshot gallery](../../../test-results/historical-reports-browser/index.html)

The separate existing native browser/Telegram report journey passed again. It
checked default historical exclusion, explicit inclusion, separate historical
timing, Complaint ID detail links, return navigation and downloaded XLSX content.
The existing implementation was retained rather than duplicated.

Focused signed-API checks cover stage ownership, stale revisions, exact replay,
different-payload replay rejection, order/finance blocking, old-hold recovery,
clock exclusions and publication reservation. The parallel-register regression
first reproduced the original 409, then passed with same-register exclusion.
Another scenario completed Eco-conserve projection while Master Data remained
held in review, then completed Master Data and verified both cases survived.

## Delivery boundary

Apply core migration **0213_jawabufarmermaster_withdrawn_stage** through the normal
deployment migration step. No production deployment, operational deletion,
customer-data correction or live Google/Telegram write was performed. Approved
visual baselines and the Phase 6 migration hold are unchanged.
