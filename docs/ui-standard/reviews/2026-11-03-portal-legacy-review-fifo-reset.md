# Legacy review, automatic FIFO publication and reset recovery

The user requested half-width ROW, recognizable review cards, specific identity
warnings and editable source cells. Subsequent production feedback clarified
that saved cases must start syncing immediately in FIFO order, including earlier
imports. A separate reset failure incorrectly classified historical HB actions
without a requisition as another group's signed order.

This supersedes the earlier all-source-rows prerequisite for ordinary legacy
Sheet sync. Full-register replacement remains a separate reviewed operation.
The compact Portal/FarmUp art direction is retained. No new dependency, model,
migration, approved baseline, candidate token or Phase 6 gate change.

## Review interactions

- ROW is fixed at 32 px, half its previous 64 px, while retaining its details
  button and accessible label. Review cards show red Blocked or amber Needs
  review labels, borders and backgrounds. Meaning is also expressed in text.
- Source-field issues show the actual value and reason. Affected grid cells
  use FarmUp's invalid-cell styling. Corrected cells use its edited-cell styling;
  tooltips and row details preserve the original value.
- Identity review lists the matching National ID, case reference, name and phone
  beside the current source values. Other source rows with the same ID are named
  by source row and customer. Matching IDs can represent additional units; the
  UI instructs staff to keep correct IDs and use explicit linkage/unit notes.
- Imported cases do not warn about matching themselves. Matches are constrained
  to the authorized owner. Ready means unimported rows ready for import; Warnings
  includes live identity matches, source duplicates and held commit failures.
- Double-click a pending mapped field, including a blocked monetary field, and
  choose **Save corrections**. Values also save before changing page, filter,
  source or layout. The server recomputes the same proposal/validation used by
  staging. Changes clear that row's approval, retain actor/time and before/after
  values in the existing draft evidence, and preserve the original XLSX chunks.
  Source Row, Case ID, imported rows and active processing remain read-only.
  Unknown fields, foreign rows, stale revisions and unrelated workflow roles
  cannot edit. Failed saves retain unsaved values; explicit refresh confirms
  their discard. Summary polling does not advance the edit revision.

## FIFO sync and recovery

- The actual importer starts a sync pass after each successful canonical commit
  chunk and before continuing the next chunk. Selecting a saved upload also
  resumes its earlier unsynced commits. No reupload or all-source-row completion
  is required. Existing controls remain recovery actions.
- The durable queue orders committed drafts by actual commit time, then draft
  key. It uses the same register-bound lease, ten-second FIFO pacing and eight-second
  provider budget. Sheet identity scanning reads only the immutable ID columns, at most 1,000
  rows per step. Publication prepares at most fifty FIFO cases, three seconds
  of preparation or a 512 KiB plan per bounded provider batch. Row reads use
  batch requests. Full replacement keeps its existing four-second pacing.
- Writes prefer an existing immutable case-row binding. An unbound original
  Source Row must be blank or confirm the reviewed identity through National ID
  or name plus phone. An occupied foreign row is refused. Unimported rows,
  counterpart tabs and unmapped cell values/formulas are preserved. Headers gain
  immutable Case ID and Master Record ID columns when absent.
- Before writing, the exact target rows, proposed values and prior checksums are
  saved. A write uses only changed cells and checks for intervening Sheet edits.
  Lost acknowledgements retry the saved plan, inspect readback and reuse the
  same rows. Verified per-draft receipts drive the synced count; publication
  permission alone is not a receipt. The oldest failed work stays ahead of newer
  cases. Queue state survives refresh and worker replacement.
- Processing remains request-assisted. Keeping the page visible runs the loop;
  closing/backgrounding pauses after the in-flight step. Resume continues from
  server evidence. No background worker, cron or production deployment is implied.
  Normal Portal publication remains held during partial cutover. Once every
  source row is saved and verified, the import completes and releases its hold.

## Reset correction

The reset guard now checks cross-group signed-order ownership only when the HB
action actually has a requisition link. Historical baselines instead retain
their legacy provenance. A genuine foreign order or cross-group legacy evidence
still blocks before Sheet deletion. The reset manifest includes legacy imports;
the confirmed owner reset removes their drafts, chunks, events and checkpoints
within the same database deletion transaction, clearing obsolete import holds.
Immutable compliance evidence and other owners remain. Source spreadsheet rows
without provable canonical IDs are retained; only exact canonical UUID rows are
removed. The reset still requires an active Superuser, backup reference and
maintenance. Failed reset maintenance is not silently disabled.

## Evidence and limits

- `test-results/portal-legacy-review-red.log`: source correction did not exist
  and identity payload lacked meaningful values before this change.
- `test-results/portal-reset-legacy-red.log`: the exact reported signed-order
  ownership message reproduced with a legitimate legacy HB baseline.
- Signed-HTTP/PostgreSQL checks cover corrections, source retention, approval
  invalidation, allowed/denied scope, live review filters, FIFO commit ordering,
  partial sync, lost acknowledgement, identity collision, reset ownership and
  existing full-replacement guards. Logs are under
  `test-results/portal-legacy-edit-fifo-reset-final-api.log`.
- Real Playwright uses actual Django sessions, signed Telegram API transport,
  AG Grid and the Admin confirmation form. Only Google is simulated. Galleries:
  `test-results/legacy-importer-automated-browser/` (50/50 verified with eleven
  remaining, lost-ack recovery, interrupted import and 61/61 completion),
  `test-results/legacy-importer-review-browser/` (32 px ROW, warning/blocked cards,
  matching values, corrected fields, originals, reapproval and reload), and
  `test-results/legacy-importer-reset-browser/` (real reviewed Admin reset of a
  legacy HB case, removal of its hold and retention of another owner's case).
  Width captures include 320, 390 and 1280 px. Source files are ratchet-bound.

Final combined verification passed **78 checks**, including three actual
Playwright journeys and independent-worker contention. The final transcript is
`test-results/portal-legacy-review-fifo-reset-final.log`; the combined screenshot
gallery is `test-results/portal-legacy-review-fifo-reset/index.html`. Django,
migration drift (no changes), JavaScript syntax, the 217-route inventory, UI
source ratchet and whitespace checks passed. The full repository suite was not
run for this bounded change.

No live upload, production database, Google Sheet or maintenance setting was
changed. Physical Telegram-device behavior and production provider throughput
remain unverified. The user's live maintenance lock must be resolved separately
after deployment before live writes can resume.
