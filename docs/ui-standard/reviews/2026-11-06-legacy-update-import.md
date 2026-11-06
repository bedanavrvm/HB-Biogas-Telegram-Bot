# Historical workbook amendments

The approved change adds **Update Existing Cases** to the existing Portal Legacy
Import workspace. It reuses the source-bound upload, mapping, AG Grid, row dialog,
checkbox, confirmation and saved-progress patterns. No design migration or
workflow role activation is introduced.

## Operator flow

1. Select the Portal owner and register, then **Update Existing Cases**. Upload
   the updated raw workbook or a reviewed comparison workbook. The same file can
   supply Master Data and Eco-conserve through their independent sessions.
2. Accept the header mapping and let staging/comparison finish. The default view
   contains changed cases only. Counts separately identify unchanged records,
   new records and matches needing review. Physical row order is not identity.
3. Cells show **database value → uploaded value**. Open Row to select fields;
   blank replacements, invalid values and unchanged-source/app conflicts start
   unchecked. Select all changed cases or individual rows, then **Apply Selected
   Changes**. No correction-reason entry or additional risk-category review is
   required. Ambiguous cases require an exact offered match; new cases require
   their own explicit confirmation. They are never included by Select All Changed.
4. Saved changes publish through the existing paced Portal publisher. The page
   shows applied/synced counts; pause or close and resume the saved upload later.
   A later app edit superseding a queued revision is followed to its current
   publication. Permanent publication failures remain visible in App Status.

## Data and workflow boundaries

Update sessions have an immutable mode and cannot delete cases, replace a Sheet,
or acquire a register fence. Existing initial-import verification holds still
apply to affected cases. Unmentioned rows survive. Source bytes and original
LegacyRow values remain retained; accepted source amendments are append-only
events. Native app-created cases retain their origin classification.

Matching is owner/register-scoped: Case ID, National ID with unit/contact
disambiguation, then matching phone plus name. Name-only and serial-only evidence
produce candidates. Phone/date/money/text equivalence suppresses formatting-only
differences. Retained Original identity cells and reviewed historical location
detail prevent undoing established cleanup. Previously unmapped reference columns
remain upload evidence rather than acquiring a new operational meaning.

Case changes recheck workflow revision under a row lock. A stale comparison must
be refreshed and selected again. Existing case correction, HB deposit and HB
action validators own their fields; live order/invoice/payment evidence cannot be
rewritten by a historical upload. Source decision wording is retained as reported
history, never fabricated current approval, signature or approval-actor evidence.
Formula expressions are not executed: updates use saved cached values and reject
operational formulas without results. Recalculate/save the source in Excel when
its cached values need refreshing.

Deployment requires `portal_legacy.0007_update_mode`. Initial uploads retain their
existing mode and destructive controls; update mode is a distinct create option.
No production import or external write is performed by deployment itself.

## Evidence

Ignored artifacts under `test-results/table-layout-review/` use synthetic records
against real Django/PostgreSQL and signed Telegram HTTP. External sockets were
denied; the Sheet transport was an in-memory implementation with actual publisher
schema validation, update and readback.

- `legacy-update-browser-result.json`, captures 16–18: header mapping, changed-only
  table, per-field deselection, approval, reload/resume, same-row Sheet update,
  no duplicate, new-case retention and no deletion/replacement controls.
- `portal_legacy.tests_updates`: equivalence and swapped headers; original identity
  cleanup; cached formulas; selective updates/blank protection; concurrency,
  resumable/idempotent application; new-case consent; register/owner/workflow
  authorization; append-only source evidence; publication reservations.
- Twenty-seven focused update/review/row-sync regressions passed, followed by an
  additional passing duplicate-match resolution test. They include HB validator
  integration, app-origin retention, superseded-publication recovery and amended
  historical receipt readback during a later initial projection.
- The supplied workbook decoded all 4,117 named Master Data and 163 Eco-conserve
  rows without decoder errors. No customer row values were logged or committed.
- The broader 95-test Portal Legacy run had 91 passes, three opt-in skips and one
  independent-worker timeout. That timeout repeated with unchanged HEAD service
  implementations loaded in an isolated test process; it is not counted as a pass.

Local synthetic checks do not certify production database comparison, live Google
connectivity or deployment. The current publisher still advances through visible
authorized Portal sessions; closing every session pauses remote work, not saved
database changes.
