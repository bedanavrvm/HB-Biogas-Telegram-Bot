# Complaints.xlsx: historical importer assessment

Inspected 3 November 2026. The user subsequently approved implementation, with
them cleaning Status and Date Reported first. See the [implemented importer](complaints-legacy-import.md).
The original workbook remains unchanged; no operational cases or provider data
were imported. The source assessment below remains historical evidence.

**A dedicated historical Complaints importer is feasible.** It needs a governed
review path because this workbook cannot pass current new-complaint validation.
It must retain unknown facts rather than manufacture identifiers, workflow
events, staff attribution, closure dates or verification.

## Actual source

Workbook SHA256:
53f4f2130b9c560082c0cf8e1dd79de2abed24bf0b1b7ee9b4718deac5de189b.
One tab: Case Management, 1,006 populated data rows and 13 named columns.
These are source rows, not a promise of 1,006 distinct valid complaints.

Excel declares 1,033 rows by 16,381 columns, although the last populated value
column is AG (33). There are 16 values beyond P, all on source row 14. G has
51 populated cells without a heading; L has three; H has none. Preserve these
unmapped cells with their coordinates for review. Blindly materializing the
declared worksheet rectangle wastes memory; limiting parsing to the 13 named
fields would silently lose data. Read bounded row fragments and retain unmapped
values as source evidence.

Local aggregate evidence is test-results/complaints-workbook-assessment/summary.json.
Review coordinates are in review-row-coordinates.json. No customer names,
identifiers, phone values or free-form complaint prose are copied into this
checked-in document.

## Data readiness

| Finding | Count / consequence |
| --- | --- |
| CASE STATUS starts with Closed | 957; reported historical closure, requiring policy for unknown completion dates |
| Open / pending | 18 |
| Blank status | 19; do not assume Open or Closed |
| Other nonstandard status | 10; call outcomes, diagnostics and fulfillment notes need review |
| Marked Duplicate | 2; a label does not identify the original case |
| Populated closure dates | **0**; do not invent timestamps or duration |
| National ID, County, Branch columns | **Absent**; applies to the whole workbook |
| Missing customer names | 2 |
| Missing Case Subject | 105 |
| Missing Constituency / Village | 114 / 375 |
| Missing Case Date | 3 |
| Date cells accepted by the current Portal parser | 918 |
| Additional dotted date strings with a clear supported date | 82; add explicit dd.mm.yy / dd.mm.yyyy support for this source |
| Other date problems | 3: A43 and A44 contain two dates; A92 has an incomplete year |
| Primary phones | 971 valid single contacts, 11 cells with multiple complete contacts, 4 needing review, 20 blank |
| Secondary phones | 768 valid single contacts, 22 cells with multiple complete contacts, 44 needing review, 172 blank |
| Numeric Village cells | 16; possible shifted data, requiring inspection |
| Exact duplicate groups | 2 pairs: rows 680/682 and 831/832 |
| Similar name/date/phone/subject groups | 4 pairs, including those exact duplicates; the others are 694/700 and 695/701 |

The two date cells containing two dates cannot establish whether the second
date is a follow-up, reopening or closure. Preserve both and ask for their
meaning. The incomplete year must remain a review issue. The 1,000 other
populated dates are readable with the explicit formats above; retain day-level
precision instead of claiming an original reporting time.

CASE STATUS and HBG Case Status Re-Confirmation disagree in one row under the
proposed simple grouping. Fourteen Closed-labelled rows contain follow-up
wording. These are review candidates, not automatic reopening decisions: the
notes may summarize events from different times. Do not reconstruct a timeline
from undated text or override the recorded status by a loose keyword match.

Some short numeric values in secondary-phone fields may be identifiers or
truncated phones. Neither length nor a nearby column authorizes relabelling
them. Preserve the original cell and review it. Split complete phone lists
without discarding extra contacts; keep their original primary/secondary source
position. Multiple contacts do not prove spouse/next-of-kin roles or ownership.

## Proposed mapping

| Source | Complaints destination / treatment |
| --- | --- |
| Case Date | Original reported date, with date precision and source cell retained |
| FARMER | Customer name |
| Constituency | Historical sub-county label; offer canonical location candidates for review |
| Village | Historical location detail; preserve numeric/shifted exceptions |
| Mobile 1 / Mobile 2 | Primary/secondary contacts, valid phones normalized to 254; invalid originals and extras retained |
| Case Subject | Complaint description; category is a separate reviewed selection |
| Jawabu Comments (Feedback) | Historical JBL note, distinct from the complaint description and HB response |
| HBG Case Status Re-Confirmation | Original status/feedback evidence; compare against CASE STATUS |
| Case Closure Date | Unknown throughout this workbook |
| CASE STATUS | Proposed Open/Closed or explicit review requirement; retain original wording |
| HB Comments | Historical HB-source note, without inventing a staff author or comment timestamp |
| JBL Comments | Historical JBL-source note, without inventing verification acceptance |
| G, L, R:AG and other unmapped cells | Source-only facts, visible for review |

Do not copy the subject into both description and a category field. Do not label
all JBL comments as satisfactory verification; the management verification
policy is distinct. Import evidence should record today's uploader and import
time, while historical note authors/times remain unknown. Chronological history
may show one explicitly labelled imported snapshot, rather than fictitious
staff actions spread over guessed dates. Attachments absent from this workbook
cannot be recreated from references in comments.

## Backend fit and safeguards

Current validate_new_case_fields in core/services/complaint_cases.py requires
National ID, valid contacts, branch, county, constituency, village, category and
description. All records lack an explicit ID field, county and branch. A
legacy-only exception is a backend policy addition requiring a user decision;
weakening normal intake would be inappropriate. Phone/name matches against
Master Data can be review suggestions; they must not silently fabricate or
replace National IDs or merge customers.

ParsedMessage and ComplaintCaseControl already retain complaint state, contact
details, resolution facts, references and current workflow control. Historical
case references should use the normal global CMP allocation, with separate
immutable workbook/owner/source-row provenance. A stable source namespace and
original Source Row must survive workbook cleanup/reordering. File hashes
identify versions; they must not create duplicate cases on every corrected file.

core/services/complaint_imports.py is explicitly read-only compatibility code:
new archived WhatsApp batches and claims are rejected. Its historical models
are not a current spreadsheet importer. Keep that retired route retired. A new
bounded Complaints legacy domain would own upload/staging/review/recovery and
call the owning Complaints workflow through an explicit audited import seam.
Any new persistent models need the repository's bounded-domain metadata and
checked-in migrations.

There is also a timing presentation issue to address before importing closed
records with unknown dates: case_timing correctly returns unavailable duration,
but serialize_case's age label falls back to today when a Closed case has no
date_resolved. That can display a misleading Closed after X days. The legacy
UI/reporting path must show **Closure date unknown** and exclude unverifiable
durations from resolution/SLA metrics. Never insert today's date as a fix.

Recommend a dedicated Complaints **Legacy import** page with upload, original vs
proposed values, table/cards review, explicit held rows and separate bounded
commit/publication. Reuse Portal's bounded upload/review patterns; keep grants,
case models, statuses and destinations owned by Complaints. Default to existing
Complaints Superuser/IT authority subject to explicit approved policy, not Portal
IT access. Preserve current cases; the Portal's earlier test-deletion permission
does not authorize deleting Complaints records. No Sheet replacement or existing
case overwrite should occur without its own reviewed impact/conflict decision.

## Approved implementation and remaining operator review

Historical gaps are warnings; Status and Date Reported remain required. Normal
new complaints retain their strict validation. The dedicated importer now uses
the app's current 22-column register schema, with explicit legacy header aliases.
No old complaint deletion, existing-case overwrite or Sheet replacement was
introduced. Staff select an already configured Complaints owner/destination.

A read-only run of the actual importer decoder retained all 1,006 populated
source rows despite Excel's inflated dimensions: 878 warning rows and 128
blocked rows before your cleanup. This does not approve those rows or establish
that they are distinct cases. Original bytes have the same SHA256 above; zero
canonical/provider writes occurred. Aggregate evidence:
`test-results/complaints-workbook-assessment/import-parser-check.json`.
