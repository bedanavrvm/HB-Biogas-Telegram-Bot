# Historical report provenance, IT corrections and Complaints reset

The user's approved plan keeps historical imports out of reports by default,
allows factual historical data and available timing on demand, and separates
historical estimates from app performance. Follow-up requests add a Complaints IT
pencil editor and repair configuration-scoped local database reset.

## Behaviour and source choices

- Complaints Telegram/browser and Portal use the same explicit historical scope
  for summaries, tables, chart selections, comparisons, XLSX and on-demand email.
  Scheduled reports default to exclusion. Existing retained snapshots are unchanged.
- Historical origin comes from import provenance, not guessed customer data or
  missing fields. Normal FarmUp intake remains ordinary app workflow data.
- Historical timings use valid recorded dates, never import execution time. They
  remain labelled approximate, including date precision and missing hold history.
  SLA comparisons without retained historical targets use current targets and say so.
- Complaints reporting reads the original target from the creation audit. A later
  target change cannot rewrite that SLA result. Missing target evidence produces
  an estimate outside the measured compliance denominator. Empty samples remain
  unavailable. Historical and app timings are never silently averaged together.
- Portal initial response uses HBG-to-JBL visit dates where available; exact native
  event timing remains available when those dates are missing. Approved native
  holds are excluded; historical missing holds are not invented. Future/reversed
  intervals do not produce valid performance samples.
- Complaint ID is an explicit detail action in both grids. Report state survives
  returning from details. Existing authorized detail resolvers supply access.
- The IT pencil editor reuses existing compact action forms, revision checks,
  recoverable saves and History. It requires a reason, validates changed values
  and date chronology, retains before/after evidence, and queues publication.
  Status, actor, import provenance and targets are not editable through it.
  Ordinary Manager/Officer and other-workflow IT grants do not authorize it.
- A correction is not a closure or HB response. Resolution text, original clocks
  and status remain intact unless the reported date is explicitly corrected.
- Confirmed local reset includes the selected group's legacy upload/row and
  durable evidence-upload dependencies. Cross-group links still block atomically.
  Other groups, shared identities, access grants and external files survive.

The controls reuse existing filter bars, input spacing, dialogs and colour rules.
The editor uses a compact responsive grid. No new design token family, approved
baseline replacement, Phase 6 migration or production activation is included.

## Native browser evidence

Playwright runs the actual Django/React/Telegram applications with PostgreSQL,
signed Telegram authentication, native password/MFA/CSRF and an independent Django
admin session. Only synthetic records are used; external network traffic is denied.
The run verifies default exclusion, inclusion, separate 48/120-hour Portal response
samples, complaint links, both IT editors, correction history, back navigation and
the admin reset form. Screenshots cover desktop and mobile. No browser script
errors were observed in the completed journey.

Artifacts: [screenshot gallery](../../../test-results/historical-reports-browser/index.html).
The JSON result and logs in that directory/parent record the actual run. API and
service regressions separately cover stale revisions, exact replay, invalid dates,
Manager denial, immutable resolution details and target snapshots, partial timing,
XLSX origin fields and cross-group reset rejection.

Final verification on 5 November: the native Playwright journey passed in 21.852
seconds with no script errors. Fifteen screenshots include light/dark, desktop/mobile,
both correction forms, correction history and the admin reset. The actual downloaded
Complaints and Portal workbooks were opened and checked for expected source records
and origin columns. The global Complaints workbook includes the separate historical
reset-fixture case before its confirmed deletion; that is intentional report scope.

TypeScript, ESLint, the pinned Node 22 production browser build, source-ratchet and
whitespace checks passed. The wider 101-check run has 96 passes and five existing
failures: native full-search scope, queue navigation scope, recovery totals,
keyset-history scope, and an older synchronous-publication expectation. Each of
those five failures was reproduced with the original `fc65ce0b` services loaded
from Git without modifying the checkout. Their baseline log is
`test-results/history-baseline.log`; they are not counted as passes.

Timing fixtures now explicitly retain creation targets, matching real intake;
the batched-query assertion includes the new original-target query. The county
label expectation follows the already-approved uppercase location catalogue.
No production case values or accepted screenshot baselines were changed.

## Boundaries

No production deployment, operational reset, provider write or real email delivery
was performed. Historical timings remain estimates. New report origins and timing
notes are additive fields; no persistent schema migration is needed.
