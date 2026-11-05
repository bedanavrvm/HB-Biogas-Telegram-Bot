# Complaints historical workbook import

Implemented following the user's approval on 3 November 2026. Clean the source
**Status** and **Date Reported** columns before import. The original
`Complaints.xlsx` remains unchanged; implementation does not import it.

## Open the workspace

- Telegram Complaints: **Settings → Legacy import**. It opens a dedicated page
  inside the existing signed launch. Closing it returns to Complaints.
- Admitted company browser: **Workspace tools → Legacy import**. Existing
  password/MFA, workflow authorization and CSRF checks remain required.

Import requires active, whole-workspace **Complaints IT** authority or an active
Superuser, and the owning Complaints capability. Portal, Origination and TAT IT
roles confer no import authority. The checked-in migration adds
`complaint.legacy.manage` to built-in Complaints IT permissions; no staff grants
are created. Deploy with the normal `python manage.py migrate` release process.
Browser release flags keep their existing default-off configuration.

The one-time **Prepare test-data changeover** action additionally requires an
active Superuser, matching the Portal test-cleanup policy. It discloses the exact
workspace, test-case count, retained import count and Sheet destination before
deletion. It preserves already imported cases, source workbooks, independent
audit records and Drive files. Only the selected Complaints tab is cleared.

## Workbook contract

Download the template from the page. It follows the app's current **22-column
Complaints register**, defined in `core/services/sheet_schema.py`:

`#`, `Complaint ID`, `Date Reported`, `Status`, `Customer Name`,
`Customer National ID`, `Primary Phone Number`, `Secondary Phone No`, `County`,
`Constituency`, `Village`, `Branch`, `JBL Reported By`, `Complaint Type`,
`Complaint Description`, `GPS Link`, `Resolution Details`, `Resolution Comments`,
`JBL Verification Comments`, `Date Resolved`, `Days Open`, `Resolution History`.

The template adds **Source Row** as column W for stable historical provenance;
it is never projected into the operational register. Sheet name defaults to
**Case Management**. Select the exact source worksheet if different.

| Source fact | Import rule |
| --- | --- |
| Status | Required: OPEN, CLOSED or REOPENED, case insensitive. Literal PENDING maps to OPEN. Prose such as “Closed, customer confirmed” must be separated manually. No status is inferred from comments. |
| Date Reported | Required original date. Excel dates, ISO, day/month/year, dotted day.month.year, the current projected date format and `24-May-2026` are accepted. Invalid, multiple or future dates block the row. |
| Date Resolved | Optional for historical Closed cases. If supplied, it must be a real date between Date Reported and today. Open/Reopened cases must leave it blank. |
| Closed with no Date Resolved | Warning; UI displays “Closure date unknown”. Days Open and unverifiable resolution/SLA outcome stay blank/unknown. Today's date is never invented. |
| Missing identity, name, location, subject | Warning; original facts remain available. No biography, customer identity match or location is invented. Normal new intake requirements are unchanged. |
| Phones | Valid Kenyan phones normalize to 254…; invalid original values remain with a warning. Slash-separated extra contacts remain in retained source evidence; the first valid number occupies that phone slot. Primary and secondary ownership is not guessed. |
| National ID | Invalid or multiple IDs remain in source evidence with a warning; they do not create a fabricated canonical identity. |
| Comments | Resolution Comments retain HB comments; JBL Verification Comments remain separate. Older JBL feedback and undated history remain historical history, without invented verification or staff actions. |
| Complaint ID | The original is retained. Complaints allocates normal CMP references; an ID already present in this workspace is held for reconciliation. |
| Days Open / # | Retained as source facts. Timing and current row numbering are computed by the app. |
| Unmapped cells | Retained by source coordinate and visible in row comparison. They are not silently assigned a meaning. |

Legacy headers such as `CASE STATUS`, `Case Date`, `FARMER`, `Mobile 1/2`,
`Case Subject`, `Case Closure Date`, `HB Comments`, `JBL Comments`,
`Jawabu Comments (Feedback)` and `HBG Case Status Re-Confirmation` have explicit
aliases. Duplicate mappings and formulas in authoritative status/date fields
are rejected. The original XLSX bytes are retained privately.

## Review and save

1. Keep one stable source namespace for this changeover. Upload the cleaned XLSX.
2. Inspect the source-to-register mapping, then stage rows. No cases are saved yet.
3. Review **Table** or **Cards**, with 50 rows per server page. Table sorting and
   column filtering apply to that page; the review filter applies to the upload.
   Open a row number to compare all original and proposed values.
4. Approve individual, displayed or all valid pending rows. Choices are saved
   server-side. Blocked rows cannot be approved. Warnings require your review.
5. Before the first import, use **Prepare test-data changeover** as a Superuser.
   Pause manual edits to the named worksheet and confirm the disclosed action.
   The app backs up Sheet values privately in PostgreSQL, removes the confirmed
   test cases in bounded chunks, clears below the existing header, verifies the
   clear and republishes any previously imported cases. Other worksheets survive.
6. Confirm **Import approved cases**. Approved rows become canonical cases and
   sync automatically after each saved batch. The original reported date drives
   age; uploader and actual import time remain separate audit evidence.
7. Watch **verified in Sheet / awaiting sync**. Verification requires readback of
   every projected field. Resume an existing import and use **Sync imported cases
   to Sheet** for older saved cases; no reupload or repeated source review is needed.

“Queued” means publication was requested; it does not mean Google accepted it.
Lost provider acknowledgements leave rows pending; retries find their Complaint
IDs and update the same rows. After clearing, new rows start immediately below
the header and remain consecutive. Source worksheet row numbers never allocate
destination rows. CMP references stay unique; consumed test references are not recycled.
The destination must have the app's current 22-column register schema, including
JBL Verification Comments. Adapt an old 13-column tab before changeover;
destination and duplicate-column validation still apply. Reordered named columns
are supported. Changeover cannot clear the register again after completion.
During interrupted changeover, **Prepare test-data changeover** can review changed
Sheet/test facts again; prior backup versions survive. Confirmed changeover cannot
be discarded.

## Corrections, duplicates and recovery

Keep **Source Row** stable across source versions and sorting. If absent, the
physical Excel row is its initial identity. Before reordering a corrected file,
populate Source Row with its previous source row numbers. Changing source
namespace/row identity can create a distinct complaint: it is not a dedupe key
based on customer identity, since one customer may have several real complaints.
Identical facts repeated within a worksheet are held for review rather than
silently treated as separate cases.

Reuploading identical bytes resumes the same upload. A corrected workbook may
reuse already imported rows with identical original facts. Changing facts of an
already imported row is blocked: use the normal audited case correction flow.
Only an uncommitted upload can be discarded. Committed provenance is retained.

Pause/closing the page stops foreground processing after the current saved step.
Reopen, choose the saved import, then resume. Uploads use checksummed 512 KiB
chunks; staging uses 250 rows/5 seconds and commits use 50 rows/5 seconds.
Sheet sync writes at most 50 cases per call with an 18-second external-call budget.
The existing scheduled publisher also resumes saved imports after the app closes:

```sh
python manage.py drain_complaint_publications --apply --limit 10 --max-seconds 50
```

Schedule it every minute. Without `--apply`, it performs no Google writes.
The open import page can also advance sync; a scheduled runner is needed for
closed-page delivery. Publication errors retain the source, saved cases and
retryable progress. Sheet clearing and writing share the database mutex with
Complaint publication, preventing stale test writes and overlapping row allocation.
An exclusive lease prevents parallel advancement; stale revisions require
refresh. After a request timeout its outcome is unknown: refresh saved progress
before retrying. Completed row transactions survive interruption.

Limits: 20 MiB compressed, 256 MiB expanded, 50,000 populated rows, 256 populated
source columns and 2 MiB per XML row. Inflated formatting dimensions are ignored.
The original workbook and checkpoints persist in PostgreSQL; the parser uses a
rebuildable private temporary disk cache. Protect host temporary storage with
the same access controls as other customer evidence. No automatic provenance
purge or production-sheet replacement is introduced.

## Verification

API/DB regressions (synthetic data; PostgreSQL recommended):

```powershell
python manage.py test complaint_legacy.tests portal_legacy.tests core.tests_portal_navigation core.tests_complaint_timing core.tests_sheet_publication --noinput
```

Real browser workflow on the repository's isolated PostgreSQL test profile:

```powershell
$env:RUN_COMPLAINT_LEGACY_E2E = '1'
node browser/scripts/build.cjs --complaints-operations --production-browser
python manage.py test complaint_legacy.tests_browser --settings=config.settings_test_postgres --noinput
```

Use the pinned Node runtime and installed Playwright Chromium. These commands
create test databases; configure `TEST_DATABASE_URL` for a disposable local test
server. Browser coverage exercises real signed Telegram requests and native
password/MFA/CSRF, saved approvals/reload, negative states, mobile review,
canonical imports, confirmed test cleanup and verified automatic sync. Screenshots and results are under
`test-results/complaints-legacy-browser/`. Provider readback uses a simulated
Sheet boundary; no production provider delivery is claimed.

### Local evidence, 5 November 2026

The changeover passed 83 scoped PostgreSQL checks plus three real-HTTP/browser
checks, including independent publishers and Playwright on both channels. The
browser removed three test cases, preserved one earlier import, verified all 63
saved complaints on the synthetic Sheet, and recovered an applied write whose
acknowledgement was lost. The gallery has 15 current captures and an inspectable
`projected-complaints.xlsx`. Logs: `test-results/complaint-projection-regression-final.log`
and `test-results/complaint-projection-browser-final.log`. UI source hashes are
recorded alongside the captures. Google transport was simulated; live delivery
and deployment remain unverified.

### Earlier local evidence, 3 November 2026

The combined scoped PostgreSQL run passed **104 tests**, including real
Playwright on both channels and an independent-worker contention check. Log:
`test-results/complaint-legacy-scoped.log`. Screenshots/gallery:
`test-results/complaints-legacy-browser/index.html` (12 captures). The browser
saved 62 synthetic cases and explicitly queued 61; the API publisher check
verified the 22-column output and replay through a simulated Sheet boundary.
The follow-up **26-test** importer API run also passed. It covers exact location
lengths, long historical descriptions and duplicate detection across staging
checkpoints. Its log is `test-results/complaint-legacy-api-final.log`.

The wider 109-test run had one unrelated existing failure:
`DatabaseCatalogueTests.test_duplicate_explicit_single_column_indexes_are_absent`
flags `core.RequisitionBatch.order_number` index
`core_requis_order_n_097497_idx`. That model/index and test predate this change;
no requisition schema was changed to silence it. Generated catalogue consistency,
metadata, Django checks, migration drift, write-route inventory, UI source
ratchet, TypeScript, ESLint and syntax checks passed.

Local runtime: Python 3.14.6, Django 5.1.6 and pinned Node 22.23.3; CI's supported
Python version remains 3.12. Remote CI, production migrations/imports, live
Google delivery and physical-device acceptance were not performed. The 50,000
row limit is a guardrail, not evidence of a full 50,000-case production import.
