# Settings recovery and legacy receipt presentation

User-approved plan, 2 November 2026. Existing Settings, App status and legacy
history compositions are reused; no styling tokens, workflow stages or
approved visual baseline changed.

Browser Settings and the existing Google Sheets sync dialog reuse the same
publication-status component. Native Settings retains its App status rows and
help dialog. Both read the durable ledger and preserve authorization, active
leases, scheduled retry delays and canonical saves.

Portal's existing legacy panel now labels genuine historical JBL receipts
separately from HB receipts and SysUp LGF. It shows review warnings for invalid
or conflicting historical amounts. The app retains the full order reference;
digits-only formatting belongs to Master Data publication.

## Evidence

Artifacts: `test-results/sheet-recovery-and-legacy-2026-11-02/`.
`index.html` links screenshots, observations and the source-bound manifest.
All data is synthetic. No test suite or assertion script was added or run.

- Native recovery returned HTTP 200 with its actual `GroupConfig`, including
  the report-delivery section that previously crashed.
- A local provider deliberately omitted JBL Verification Comments. The actual
  worker retained a safe missing-column diagnostic and marked work for review.
- Native Settings and browser Settings displayed the cause and absent heartbeat.
  Authorized retry/replay returned HTTP 200 without changing revision 21 or
  duplicating comments/evidence. Officer retry and unrelated-workflow access
  returned HTTP 403.
- A scheduled retry retained its exact original next-retry timestamp. After
  repairing the local provider, the actual worker succeeded and cleared its
  diagnostic; the original case status, report time, SLA anchor and comment/file
  counts remained unchanged.
- The actual Master projection wrote `00047` while the app/database retained
  `HB-00047`. It projected a JBL receipt of 2500.50 independently of HB 1000.25
  and LGF 7777.00; the canonical amounts were not rewritten. The first projection
  exposed existing whole-shilling rounding, which was corrected for JBL receipts.
- The reviewed-workbook parser accepted a separately named JBL receipt, rejected
  malformed amounts and flagged buyoff allocator exceptions. Portal displayed
  the separate receipt in its existing legacy panel.

Static verification includes the Complaints operations build, TypeScript,
native JavaScript syntax, Django checks and the UI source ratchet. Local actor
injection and Google substitutes were used; these do not verify production
authentication, live Google delivery, real devices or a commissioned scheduler.
The full FarmUp intake workflow was not rerun; its unchanged HB-ownership rule
was inspected, and the shared monetary projection was exercised directly.
