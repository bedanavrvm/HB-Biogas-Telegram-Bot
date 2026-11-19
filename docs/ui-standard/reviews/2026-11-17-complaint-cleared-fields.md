# Complaint corrections and Sheet refresh - 17/11/2026

The user requested a Master Data biodata notice, dependent location dropdowns
when editing complaints, reliable propagation of omissions/clears and edits in
Complaints and Portal, and history retaining the values removed. They explicitly
selected re-sync for already-saved cases whose old Sheet row is stale.

## Findings and implementation

- Complaints' publisher omitted editable location/biodata fields, while its
  strict Sheet update allowlist also excluded them. Both now project the current
  canonical values, including empty strings. Stable references and unowned
  columns remain excluded. Date cells use `dd/mm/yyyy`.
- Portal's live projection already writes blanks. Its import merge intentionally
  preserves missing source values and remains unchanged. Tests exercise an actual
  correction and clear through Master Data and Eco-conserve publication.
- Both row writers read back changed cells, including missing trailing blanks,
  before success. Numeric/date values are compared against their typed Sheet
  representation. Failed readback keeps the saved data and fails publication.
- The existing Complaints correction grid now reuses the creation form's
  dependent county/constituency catalogue. The location endpoint supports an
  authorized case editor without granting creation. Unchanged historical choices
  survive; loading errors retain edits. A stale response cannot replace a later
  selection. Fixed-format date/time inputs reuse the calendar pattern.
- The shared activity renderer previously displayed only `Village removed`.
  It now renders the saved previous value and `Not set`, with escaping and the
  existing long-text disclosure. History uses the Constituency label.
- Existing retry APIs accept an explicit snapshot refresh. The new compact
  **Re-sync to Sheet** buttons use current workflow/case permissions, coalesce
  active jobs and preserve leases/backoff. Refresh never edits case revisions,
  duplicates correction history or grants access. Operations retain actor and
  request evidence. Existing deletion fences remain in force.

Current grid, status, icon-button and history styles are reused. Asset versions
are advanced for affected consumers, including shared TAT history. No dependency,
model, migration, permission or production feature activation was added. The
earlier staged Portal chronology work is preserved. Phase 6 remains on hold.

## Evidence and validation

Playwright used the native Django Complaints and Portal shells, real signed
Telegram identities and normal authorized APIs against an isolated PostgreSQL
copy with synthetic records. External sockets were blocked. It saved cleared
constituency/landmark values, checked both removed values in history, verified
the paired dropdown/date controls, retained edits after a failed location load,
tested `23/11/2026` and `01/12/2026` transport, and queued refresh in both apps.
The source notice is verified while preserving the internal JBL reference.

Captures are source-bound synthetic evidence, not design-baseline approval:

- [Mobile correction fields](portal-ux-options-2026-10-29/assets/complaint-cleared-fields-2026-11-17/editor-390.png)
- [Desktop correction fields](portal-ux-options-2026-10-29/assets/complaint-cleared-fields-2026-11-17/editor-1280.png)
- [Removed values in history](portal-ux-options-2026-10-29/assets/complaint-cleared-fields-2026-11-17/history-390.png)
- [Portal refresh](portal-ux-options-2026-10-29/assets/complaint-cleared-fields-2026-11-17/portal-refresh.png)
- [Master Data notice](portal-ux-options-2026-10-29/assets/complaint-cleared-fields-2026-11-17/biodata-source.png)

The final combined backend run passed 139 tests, covering real gateway writes with
reordered headers, blanks, omitted fields, zero/false, ignored-write detection,
scope denials, refresh after success/replay, correction audit, typed dates and
deletion/retry protections. Internal-order publication also clears the existing
row without duplication when its identity columns are present. Fake transports
now support real readback. Old fixed-column assertions were updated for the existing Verification Comments
column; a synthetic activity fixture now supplies its required evidence relation.
Seventeen browser checks cover shared history at 320/390/430/1280px, ordinary
comments and the native journey. Local logs: `test-results/complaint-corrections-*`.

Run the native journey with `COMPLAINT_CLEAR_REVIEW_CONFIG` pointing to the
isolated fixture and `core/tests_browser/complaint_cleared_fields.spec.js`.
Backend regression entry points include `core.tests_correction_publication`,
`core.tests_sheets_validation`, the new Complaints service checks and Portal's
`test_native_correction_clears_optional_values_on_both_registers`.

Ruff, JavaScript syntax, the UI source ratchet, the write-route inventory,
migration drift and the 233-table database catalogue checks pass. The repository
artifact audit still reports pre-existing unreviewed images and older image hash
mismatches; none concerns this change or its five hash-pinned synthetic captures.

No production deployment, live Google write/readback, physical Telegram device
or bulk repair was performed. Queue completion still depends on the configured
publisher/pump and Google availability. Readback adds one row read per changed
publication. See `docs/runbooks/complaint-corrections-and-sheet-refresh.md`.
