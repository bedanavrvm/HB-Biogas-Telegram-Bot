# Complaint verification comments: implementation review

31 October 2026. User-directed extension of the existing Complaint action form,
with the supplied Stitch design authority retained. This is not approval of a
new visual baseline, Phase 6 migration, deployment or browser admission.

## UI choices

The native Telegram form retains its compact action tabs and evidence picker.
HB has Comment / Resolve; JBL has Comment / Reopen. Reopen is disabled on open
cases. Dual-role staff choose HB or JBL comment explicitly. Labels identify the
owner of the note. Camera/upload icons reuse the existing Lucide symbols.

The standalone operations workspace uses its existing action dialog, picker,
sticky footer, notices and recovery state. Its tabs follow the same ordering.
The existing history renders attachment galleries against the corresponding
comment, using the authorized browser media transport. A previously undefined
media-progress comment key is now carried through the gallery/viewer. Ordinary
conversation and its closed-case restriction remain separate.

No new colour, spacing, font, icon dependency or design-system token set was
introduced. The shared dialog's existing top-placement geometry moved to a
native style declaration because the ADS CSS type rejected those exact values;
the geometry is unchanged. The new report column uses existing wrapped cells.

## Evidence

Local artifacts: `test-results/complaint-verification-review/`.
Open `index.html` for the screenshot gallery; `source-manifest.json` binds final
UI hashes and image hashes. Artifacts are synthetic and ignored by Git.

| Review | Observed result | Artifact |
| --- | --- | --- |
| Officer comment on a closed case with PNG | Save succeeded, status remained closed, history bound the file to the comment | `01-officer-comment-with-attachment.png`, `02-officer-closed-history.png` |
| Manager reopen, HB comment with PDF, final HB resolution | Original 3-day closure became an 8-day final closure after reopening | `walkthrough-cycle.json`, `03-manager-reopen.png`, `04-hb-comment-pdf.png`, `05-hb-final-close-history.png` |
| Officer, Manager, IT and dual-role post-closure comments | Saves succeeded, closure stayed at 8 days | `walkthrough-cycle.json`, `06-*-mobile-comment.png` |
| Unrelated workflow grant and foreign group | Access denied | `07-unrelated-workflow-denied.png`, `negative-and-recovery.json` |
| Concurrent comment | HTTP 409 retained text/file; review latest and save succeeded | `10-stale-revision-draft-retained.png`, `negative-and-recovery.json` |
| Disguised PNG and blank comment | Rejected without clearing the draft | `11-invalid-evidence-retained.png`, `negative-and-recovery.json` |
| Native JBL/HB comments with files and dual-role selection | HTTP 200, fields cleared after confirmed save; correct tabs and labels | `native-observations.json`, `12-native-*-attachment.png`, `13-native-*-history.png` |
| Native reopen, final HB close and closed-case JBL comment | 8-day anchor retained and latest HB note unchanged by JBL comment | `native-close-reopen.json`, `14-native-manager-reopen.png`, `15-native-closed-verification.png` |
| Desktop/mobile, light/dark and enlarged text | Forms and actions remained usable; inspected screenshots | `16-*-final.png`, `final-review.json` |
| History image and PDF preview | Actual raster content loaded through scoped endpoints | `18-history-image-preview.png`, `19-history-pdf-preview.png`, `final-review.json` |
| Same request/files replay, changed files on same key | Replay kept the same revision; changed bytes rejected | `final-review.json` |
| HB closed-case comment / empty reopen reason / reopen of open case | Server rejected all three | `final-review.json`, `final-state-keyboard.json` |
| Keyboard tabs | Arrow and Home navigation, skipping disabled Reopen | `final-state-keyboard.json` |
| Provider outage and retry | Retained bytes matched SHA-256 receipt; retry published successfully | `database-publication-observations.json` |
| Sheet completes before Drive | File completion queued another Sheet snapshot containing the link | `publication-order-observations.json`, `sheet-snapshots.jsonl` |
| Export and saved schema migration | Separate JBL column, preserved date column format, named mapping added | `synthetic-complaints-register.xlsx` |

Direct PostgreSQL observations retained original report/SLA anchors, closure
timestamps, comment ownership, evidence foreign keys and chronology. Static
verification included the production client build, TypeScript, native JavaScript
syntax, Django checks/migration drift and UI source ratchet. No test suite or
assertion script was added or run.

## Limits

The walkthrough used a separate local PostgreSQL database, synthetic staff grants,
and a loopback-only actor shim. Authentication, MFA, real staff admission and
Telegram signed-launch security were not verified here. Native diagnostics
rejected the unsigned local identity as expected; operational calls used the
explicit debug-only local identity path. The review host skipped release
activation checks; ordinary Django checks ran separately with browser activation
disabled. No production flags or authentication implementation changed.

Google calls used a local provider substitute. These observations establish
canonical saves, receipt retention, retry scheduling and generated projection
values; they do not establish delivery to real Google services. Real devices,
camera capture, speech providers and screen readers were not exercised.
