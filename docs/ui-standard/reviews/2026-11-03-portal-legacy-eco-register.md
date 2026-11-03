# Legacy import: dedicated sidebar page and register selection

The user authorized Eco-conserve alongside Master Data, then clarified that
Legacy changeover must be its own sidebar section/page and the importer must
be removed from All Cases. This change reuses the existing Portal shell,
FarmUp segmented controls, compact AG Grid/Cards review, dialogs and feedback.
It changes no approved baselines or candidate tokens; Phase 6 remains on hold.

**Legacy changeover → Legacy import** is its own capability-filtered sidebar
section. It is absent from Pipeline Intake and All Cases. On mobile it remains
accessible through the existing More hub. The page selects **Master Data** or
**Eco-conserve** before upload. Saved uploads are filtered by source; switching
sources saves pending review choices and clears the prior source's visible
mapping, rows and progress. The immutable saved source also binds backend
cleanup, canonical partner and replacement destination.

Deletion impact and replacement confirmation name the selected register and
preserved counterpart. The owner-wide cutover hold still serializes operational
writes while either register is changing. The source-specific one-time cleanup
guard permits Eco after completed Master and Master after completed Eco. Table
and Cards retain their existing page limits, read-only source facts and shared
review choices. No personal source values are stored in browser preferences.

## Source bounds

Registry entries cover portal.js, portal_legacy_import.js, its CSS,
base_shell.html and partials/legacy_import.html. Navigation configuration is
core/services/portal_navigation.py. Backend source binding is enforced in
portal_legacy/models.py, migration 0006, registers.py, importer.py, services.py,
projection.py, import_views.py and the bounded worksheet decoder. The decoder
also retains Excel root namespace declarations and handles self-closing empty
rows without consuming the following customer row.

## Actual Playwright and readback evidence

The local gallery is **test-results/eco-legacy-review/index.html**. Browser
observations, JSON readback and screenshots are stored alongside it. Rehearsal
uses isolated PostgreSQL hb_legacy_eco_review_20261103 and a separate SQLite
provider simulation. The original rehearsal database/provider remain intact.
No automated test suite was added or run.

- Sidebar navigation opened the dedicated page; All Cases had zero importer
  elements. Source switches restored only the selected register's saved uploads.
  Final 320/390/1280 captures had no document-level horizontal overflow.
- A full 160-row synthetic Eco workflow completed upload, mapping, staging,
  confirmed deletion of seven Eco test cases, per-row commits and target sheet
  readback. All cases were canonically ECOCONSERVE, source provenance was Eco,
  and 160 publication bindings became ready after replacement.
- Exact hashes of all fields of the 5,000 prior Master cases matched the original
  database. The Master sheet's 5,001 rows including its header also matched the
  original provider hash. Exactly one Eco replacement was recorded.
- The reverse direction imported three Master rows after deleting three HB test
  cases in another owner; two Eco cases and its Eco sheet sentinel survived.
  Exactly one Master Secondary replacement was recorded.
- Attempts to retarget an existing upload or select an unsupported source were
  rejected with 409. Replaying identical file/owner/source reused its upload;
  choosing the other source created a separate upload and staged only that tab.
  Scoped Portal IT was admitted; Operations and Origination-only IT received 403.
- The reviewed import-ready v5 copy staged 156 Eco rows (17 warnings) and 4,077
  Master rows (208 warnings), with zero blocked rows and zero canonical commits.
  The [one-header repair](../../runbooks/legacy-eco-v5-header-review-2026-11-03.md)
  preserves all data values. Historical warnings remain for operator review.
- An actual XLSX with Excel namespace attributes and a self-closing blank row
  staged both surrounding source rows, 2 and 4, retaining their dates. The first
  candidate exposed a parser issue; the corrected decoder was rerun against the
  same edge case. Evidence records the final two rows, with zero canonical commits.
- Final workbook-to-database value comparison exposed shared historical formulas
  losing their expression after a batch boundary. Formula origins are now indexed
  in the disposable source cache and restored for every batch. Playwright staged
  both actual tabs again in a separate owner. Exact source-value hashes match all
  4,077 Master and 156 Eco rows, including all 4,077 historical formula expressions.
  Rebuilding the cache and resuming at source row 252 retains the exact saved facts.
  Zero real rows were committed. Formula evidence is retained, never executed.
- The initial index load now disables controls until ready, preventing a source
  click from being lost while handlers are attaching. Final sidebar/All Cases,
  source-switch and completed Eco-resume captures reported no browser script errors.

The earlier [table/cards review](2026-11-03-portal-legacy-grid-toggle.md) retains
selection, sorting/filtering, asset-failure recovery and 50,000-row bounded-page
observations. The [operator runbook](../../runbooks/portal-legacy-importer.md)
documents migration, source selection, cleanup, pauses and recovery.

These are local real-shell observations with simulated Google transport. Live
Google throughput, production memory headroom, full 50,000-case commit/projection,
physical Telegram devices and screen-reader review remain unverified. No real
customer canonical import, production deletion, provider write or deployment
was performed.
