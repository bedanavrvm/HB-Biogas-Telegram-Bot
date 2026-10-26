# Portal improvements: implementation and verification, 26 October 2026

The user's instruction to implement the agreed Portal plan authorizes items 1–11 and 13. Item 12, visibility of the internal JBL deposit in HB-accessible payment documents, remains explicitly deferred. This work does not activate the standalone browser client or adopt Design Lab candidate tokens, baselines or Phase 6.

## Delivered behavior

| Item | Implementation |
|---|---|
| 1. App status | Portal-specific overview with waiting, processing and needs-attention totals across all pages; scoped rows, collapsed plain-language instructions and support references. Existing repair confirmations and safe retry keys remain. A failed refresh shows an error instead of a healthy state. Technical readiness remains separate. |
| 2. Payment number setup | Initially collapsed `details`, reusing the Order numbers summary and settings layout; the summary shows the next number or a lookup failure. |
| 3. Create & visit wording | Removed the requested sentence. The server's KES 5,000 visit gate remains enforced. |
| 4. PDF rotation | Clockwise 90-degree preview rotation, refitting, zoom and pan. Orientation follows pages within the document and resets on closure/new document. Narrow controls wrap without shrinking touch targets. Selected PDFs use a bounded, authenticated, private, non-retained render endpoint. Original, signed and downloaded bytes are unchanged. |
| 5 and 7. Counties | Canonical names, codes and approved aliases share one unambiguous resolver. Queue and report choices combine equivalent spellings and filters include their historical raw values. Unknown/ambiguous entries remain reviewable. The read-only data-quality report also recognizes approved aliases without rewriting records. |
| 6. Serial No | Invoice extraction handles stacked, inline and table layouts, including glued PDF text and leading zeroes. Ambiguity remains unresolved. Accepted matching/replacement/unmatching updates the existing HB Action serial with audit history. HB installation cannot override it. Master Data adds a named Serial No column, respecting existing aliases. |
| 8. Chart types | Reused the shared chart-type SVG icons with accessible names, tooltips and selected state. |
| 9. Chart help | Each chart explains its business meaning, units, period basis and any timing measures. Reading instructions follow the selected chart's actual axis orientation or ring slices. Median, P90 and sample counts are explained. |
| 10. Reports | Compact Pipeline, Outcomes and Finance composition; four primary figures, additional figures collapsed, compact charts, existing case table, and secondary controls in their existing menus. |
| 11. Persistent filters | Shared branch/county/product/period preferences survive tabs and full page navigation within the same Portal launch. Stage/drill state stays separate per tab. Only allowlisted non-customer preferences enter sessionStorage, bound to a server HMAC of actor, policy and current capability scopes plus a digest of the Telegram launch. Searches remain memory-only. Reset clears remembered choices. Every query still checks current backend scope. |
| 12. Internal deposit visibility | Deferred. Existing payment documents/APIs can still expose the SysUp JBL deposit to HB viewers. No document-privacy policy or historical signed bytes were changed. |
| 13. HB Deposits | One cumulative amount, short status, operational date, one Save action, conditional reduction explanation and collapsed history. Existing revision, retry, scope and first-JBL-visit locks remain. |

## Deposit date and invoice ownership

`JawabuFarmerMaster.hb_deposit_date` is a nullable canonical date. Initial FarmUp totals use the accepted HBG/Sign Date; BRO intake and accepted subsequent amount changes use their Nairobi calendar date. Unchanged totals, retries, unrelated changes and rejected requests do not move it. Invoice corrections/unmatching retain the existing financial authority while dating any resulting effective deposit change. Prior values and dates remain in workflow history.

Migration `core.0209_portal_deposit_date` adds the commented field and backfills only evidence-supported dates. It does not infer an initial historical date from a customer's later current visit date or from deployment day. Malformed or insufficient evidence stays blank. Publication uses the named **HB Deposit Date** column and the existing true spreadsheet-date conversion.

There is one operational serial: `HomeBiogasAction.serial_number`. Parsed extraction stays in the invoice's existing raw payload. Missing/ambiguous replacement evidence clears the operational serial with history. No second manual serial field or conflict chooser was introduced. Existing invoice identity, replacement, signed-order and payment finality guards remain in place.

`backfill_invoice_serials` is dry-run by default, bounded to 200 actions (maximum 1,000), with an `--after` cursor. `--apply` recovers only a unique current accepted invoice's retained serial extraction, creates the HB audit event and queues Master Data publication. It does not contact Drive or Sheets. Older PDFs without retained serial extraction remain unresolved; this command does not guess from customer names, order numbers or unverified PDF copies.

PostgreSQL also revealed an existing overlength audit action in legacy deposit reconciliation undo. New undo events use `hb_deposit_review_reconcile_reversed`, which fits the existing 40-character field; readers retain support for the historical longer label. No audit-field widening or deletion was needed.

## UI sources and evidence

Existing source patterns: `portal.css` settings summaries and HB forms/history; `components.js` chart icons/help; `portal_curated_reports.js` tabs, filters, AG Grid and chart menus; `secure_media_viewer.js` page/gesture lifecycle; `miniapp_recovery.js` scoped repairs and confirmation controls. The source ratchet records current changed-source hashes as this bounded user-requested correction. Original legacy hashes, approvals and migration gates remain unchanged.

Real-shell Playwright captures use the actual Portal shell and stylesheet order with synthetic API fixtures. Light/dark reports, status and deposit screens were inspected. Rotation was checked at 320, 390 and 768 pixels; reports retain the existing 320–1280 pixel checks. Evidence is local under `test-results/portal-improvements/`:

- `browser/`: 90 focused browser checks passed, including launch/owner filter isolation and failure recovery.
- `browser-all.log`: full Portal/shared-recovery run, 325 passed and one Playwright protocol handle error in signed-payment upload. That upload scenario passed in the subsequent `browser-final.log` run. This infrastructure error was not counted as a product pass.
- `browser-confirmed.log`: 59 final report/media checks passed, including the corrected production-shaped chart fixture, accurate chart help and phone-sized rotated previews.
- `backend-third.log`: 441 affected backend checks passed on isolated SQLite, two PostgreSQL-only skips.
- `backend-final.log`: 298 latest backend/recovery/report-delivery checks passed on isolated SQLite, three PostgreSQL-only skips.
- `postgres-final.log`: 223 checks passed on a fresh isolated PostgreSQL 18 cluster, no skips. Real competing deposit edits, visit-versus-deposit changes, invoice correction races and migrations ran.
- `postgres-focused.log`: 13 subsequent PostgreSQL checks passed, including the latest county/date cases and invoice-unmatch date behavior.
- `meta-check.log`: current-scope preference-key regression passed after adding scope binding.
- `preferences-final.log`: seven final preference/navigation checks passed, including clearing stale drill buckets after changing shared time grouping while retaining each tab's stage.
- `retry-confirmed.log`: final combined backend run completed 613 tests successfully (three PostgreSQL-only skips on SQLite). This includes the last correction preserving a Sheet deposit date when an older import has no canonical date field. The isolated runner now restores its customer-free migrated baseline before each run; the earlier reused database had lost its seeded audit singleton after transaction-test cleanup.
- `journeys/volume-office-600-1793022688929471800/verification.json`: independent reconciliation passed for 600 BRO-created cases, 600 local Sheet rows, 12 signed orders/invoices and 12 completed payments/installations/commissionings; 938 integration operations succeeded. Nine invoice serials propagated and three intentionally missing serials stayed blank. Local Drive retained 236 upload references to 29 hash-verified blobs.

The connected workflow completed successfully. Its first final assertion incorrectly indexed an omitted trailing blank Sheet cell for an intentionally unresolved serial. The assertion and independent verifier now treat an omitted cell as blank, matching Sheets semantics. Original failure evidence is retained; the corrected independent verification reconciled the saved database, CSV projections, workbook checksums, invoice serials, dates and local Drive bytes without replaying workflow writes.

First-party JavaScript, Node checks, the 204-route write inventory, Django system checks and migration drift checks passed. Network connections were blocked except for the isolated loopback PostgreSQL cluster. Deployment `.env`, production databases, Google providers and real Telegram groups were not used.

## Release and remaining boundaries

Deploy the code with migration `0209`; no production migration or publication was run here. The normal durable publication path adds the new named Sheet columns and projects current values. Historical rows receive newly backfilled values when next published; no live bulk republish was authorized or performed. Review dry-run serial backfill counts before applying and continue with the printed cursor for larger sets.

Physical Telegram devices, real Google permissions/quotas and live provider delivery were not checked. Item 12 remains a known privacy exposure pending the separately deferred policy decision. Synthetic screenshots and technical checks do not constitute human design acceptance or Phase 6 approval.
