# FCA Sample Workbook Analysis

Analysis date: 27-Jun-2026

Source directory: `fca sample/`

## Files Reviewed

15 FCA `.xlsx` files were reviewed. The samples are not one single strict template, but they follow a small set of repeatable layouts.

## Common Sheet Structure

Most FCA sheets are human-formatted Excel forms, not database-style sheets.

Common pattern:

- Row 2 contains the form title and visit date.
- Row 4 contains the hub/region.
- Row 5 is usually the real table header.
- Row 6 onward contains customer records.
- Footer rows such as `TO BE VISITED BY`, `ADMIN(AFTER VISIT)`, `UPDATED ON MASTER DATA`, `APPROVED BY`, and `REMARKS` mark the end of the data table.

The parser should ignore visual/title/footer rows and only extract customer rows.

## Main Layouts Found

### 1. FCA Activity Form

Example files:

- `17TH JUNE FCA.xlsx`
- `23RD FCA after visit.xlsx`
- `FCA 16TH.xlsx`
- `THARAKA 26TH FCA.xlsx`
- `THARAKA 26TH FCA After visit (1).xlsx`

Typical columns:

| Column | Meaning |
| --- | --- |
| A | Sequence number |
| B | Customer Name |
| C | Contacts |
| D | Location |
| E | Sales Person / HB Staff |
| F | Deposit |
| G | Comment |

In these files the comment is normally in column `G`.

### 2. FCA Approval Form

Example files:

- `FCA Kiambu 23rd June 2026 after visit.xlsx`
- `FCA Nyeri 11th June 2026 AFTER VISIT.xlsx`
- `FCA Nyeri 18th-19th June 2026 collection After the visit.xlsx`
- `FCA West Nairobi Hub after 23rd June visits..xlsx`
- `MERU THARAKA FCA JUNE 17TH AFTER VISIT (1).xlsx`

Typical columns:

| Column | Meaning |
| --- | --- |
| A | Sequence number |
| B | Customer Name |
| C | Contacts |
| D | Location |
| E | HB Staff |
| F | Deposit |
| G | Approval Basis / Category |
| H | Comment / after-visit status |

Important: in several files column `H` contains comments but the row 5 header cell is blank because row 2 uses column `H` for the date. The parser must treat blank column `H` as the comment column when column `G` is `APPROVAL BASIS`.

### 3. Collection Visit Sheet

Example:

- `MERU THARAKA FCA JUNE 17TH AFTER VISIT (1).xlsx`, sheet `COLLECTION VISIT`

Typical columns:

| Column | Meaning |
| --- | --- |
| A | Names |
| B | ID No |
| C | Mobile No |
| D | Term |
| E | Installment Amount |
| F | Arrears Amount |
| G | Arrears Days |
| H | Location |
| I | Amount Paid |
| J | Comment |

This is a different record type from approval visits. It can still provide visit comments, but most comments are collection status notes, not approval decisions.

### 4. Non-Data Sheets

The `Budget` sheet in `FCA Nyeri 18th-19th June 2026 collection After the visit.xlsx` is not customer data and should be ignored.

## Fields We Can Extract Reliably

| Target Field | Source |
| --- | --- |
| FCA Visit Date | Row 2 date cell, fallback to workbook filename |
| Customer Name | `CUSTOMER NAME` or `Names` |
| Primary Phone | `CONTACTS` or `Mobile No` |
| Location | `LOCATION` |
| HB Staff / Sales Person | `HB STAFF` or `SALES PERSON` |
| Deposit / Amount Paid | `DEPOSIT` or `AMOUNT PAID` |
| FCA Comment | `COMMENT`, or blank column `H` when `G` is `APPROVAL BASIS` |
| FCA Decision | Derived from FCA Comment where safe |

## Visit Date Rules

The visit date is usually in row 2:

- `DATE…17TH JUNE 2026`
- `Date: 23rd June 2026`
- `DATE…24TH,25TH,26TH JUNE 2026`

Fallback should parse the filename:

- `17TH JUNE FCA.xlsx` -> `17-Jun-2026`
- `FCA Kiambu 23rd June 2026 after visit.xlsx` -> `23-Jun-2026`
- `MERU THARAKA FCA JUNE 17TH AFTER VISIT (1).xlsx` -> `17-Jun-2026`

The parser must support both day-first and month-first text:

- `17TH JUNE`
- `JUNE 17TH`

For multi-day labels such as `24TH,25TH,26TH JUNE 2026`, use the first listed date as the FCA visit date unless a row-level date is added later.

## Decision Extraction From Comments

Only derive a decision when the comment clearly says it. Otherwise leave the decision blank for manual review.

Recommended mapping:

| Comment Contains | Decision |
| --- | --- |
| `approved`, `approve`, `appraisal` | `APPROVED` |
| `rejected`, `reject`, `declined` | `REJECTED` |
| `deferred`, `defer`, `awaiting`, `undecided`, `requested more time`, `more time` | `DEFERRED` |
| `rescheduled`, `reschedule`, `not visited`, `not available` | `DEFERRED` |
| `opted cash`, `decommissioning`, `decomissioning` | `REJECTED` or manual review, depending business rule |

Do not blindly convert all collection comments into decisions. Examples like `ptp 22nd`, `paid 3k`, `demand issued`, or `cleared` are useful FCA comments, but they are not always final approval decisions.

## Edge Cases Found

- Some “after visit” comments are in a blank header column, usually column `H`.
- Some pre-visit files use `COMMENT` for directions/site notes, not decisions.
- Some sheets include embedded section labels such as `COLLECTIONS`, `KIRINYAGA`, or `COLLECTION`; these should not be imported as customer rows.
- Phone numbers appear as `07...`, `2547...`, plain `7...`, and sometimes multiple numbers separated by `/`.
- Some numeric phone cells are read as Excel numbers, so phone normalization must preserve leading zero/convert to `254...`.
- Some sample sheets have many blank styled rows; extraction should stop at footer markers instead of scanning the whole sheet blindly.

## Recommended Import Behavior

1. Accept one or more FCA `.xlsx` files.
2. Ignore non-customer sheets such as `Budget`.
3. Detect the layout by headers instead of fixed sheet names.
4. Extract FCA visit date from row 2, then fallback to filename.
5. Extract comments from:
   - `COMMENT` column when present.
   - Column `H` when column `G` is `APPROVAL BASIS` and column `H` contains after-visit text.
6. Derive `FCA Decision` only from clear decision words.
7. Leave uncertain decisions blank and mark the row for review.
8. Normalize names to uppercase if writing into the managed order workbook.
9. Normalize phones to `254...` format.
10. Store source metadata:
    - source file
    - source sheet
    - source row

## Suggested Order Workbook Columns

If FCA imports feed the order approval workbook, add dedicated FCA columns instead of overwriting BRO fields directly:

- `FCA VISIT DATE`
- `FCA COMMENT`
- `FCA DECISION`
- `FCA SOURCE FILE`
- `FCA SOURCE SHEET`
- `FCA SOURCE ROW`
- `FCA IMPORT STATUS`

This keeps BRO-entered data and FCA-imported data separate for comparison.
