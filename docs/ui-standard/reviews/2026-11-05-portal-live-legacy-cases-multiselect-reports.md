# Portal verified legacy cases and report multiselect

User-authorized scope: normal actions on already imported and Sheet-verified
historical cases during partial import, and checkbox filters in Portal reports.
This supersedes the whole-owner operational hold described in the earlier
parallel-cutover review. Administrative and destructive cleanup holds remain.

## Source and behaviour

- `portal_legacy/fence.py` supplies one case-readiness predicate to API admission
  and publication. Committed source linkage and initial Sheet readback evidence
  are required while the register is held. A flag alone cannot release a case.
- Existing continuation, pencil correction and workflow controls retain their
  current layout. Normal roles, revisions and request keys still apply.
  Continuation adds a pipeline event and reserves durable publication. Import
  progress and original source facts survive subsequent case edits.
- The request guard resolves route-bound cases, saved order/document membership
  and signed requisition selections. Mixed selections are checked before writes.
  Supplying a fabricated case ID to a settings payload cannot bypass its hold.
- `row_sync.py` retains the durable write plan before Google calls, locks canonical
  records in a consistent order and refreshes stale plans from current Django
  values. Unknown external changes still stop for review. Corrected canonical
  phones/deposits take precedence over retained source facts in replacement.
- Full-register replacement pauses only its affected register from confirmation
  through successful readback. Destructive test cleanup and unresolved initial
  writes retain their safety holds. Ordinary incremental sync does not impose a
  whole-import wait on verified cases.
- `portal_curated_reports.js` adapts the existing filter dialog into four compact
  checkbox groups, with selected counts and a per-group Clear action. OR applies
  within Branch, County, Product or Stage; AND applies across those groups.
  Dates and the historical-data toggle retain their existing meaning.
- Array selections persist across reload, detail/back and report-tab navigation.
  `portal.js` waits for the account-bound report session key before mounting the
  report workspace, preventing anonymous-key persistence during startup races.
  Scalar API filters remain accepted. Invalid arrays are rejected server-side;
  authorization scope applies before report filters.
- Charts, rows, drilldowns and XLSX use the same filter input. Email scope copy
  presents array selections as readable lists. No font, shell, spacing or token
  redesign; scoped CSS keeps checkbox groups usable at 390 px and 1280 px.

## Evidence

Actual Django pages, signed Telegram authentication and a dedicated local
PostgreSQL database were used with synthetic cases. Playwright exercised:

1. Continuation while another source row remained unimported.
2. IT pencil correction, withdrawal and same-case resume during that import.
3. Return to the original saved import without uploading or reviewing it again.
4. All four checkbox groups, OR and AND results, real XLSX download/readback,
   email dialog selection, reload, detail/back and report-tab persistence.
5. Desktop and mobile screens, with no uncaught page script errors.

- [Screenshot gallery](../../../test-results/ready-cases-browser/index.html)
- [Playwright result](../../../test-results/ready-cases-browser/result.json)
- [Canonical database readback](../../../test-results/ready-cases-browser/database.json)
- [Projected local Sheet](../../../test-results/ready-cases-browser/local-sheet.xlsx)
- [Filtered report workbook](../../../test-results/ready-cases-browser/filtered-report.xlsx)

Database readback confirms the corrected phone, audited continuation and workflow
actions, with four successful publication operations. Local Sheet readback has
one bound row containing the corrected phone, while the source value is retained.
Focused integrity checks separately cover stale plans, lost acknowledgements,
unverified/mixed selections, document membership, role denial and malformed
filters. These complement the real browser journey.

## Delivery boundary

No schema migration is introduced. No production deployment, live customer edit,
Google/Drive write or real email send was performed. The local Sheet boundary is
synthetic; live provider availability and production concurrency are not certified.
Approved visual baselines, candidate tokens and Phase 6 migration remain unchanged.
