# Order Approval Apps Script

This guide documents `order_approval_apps_script.gs`, the Google Sheets Apps
Script used with the Order Approval spreadsheet.

## Purpose

The script improves the live Google Sheet around the bot workflow:

- Adds the `Orders` custom menu.
- Normalises manual sheet edits.
- Highlights pending and stale order rows.
- Applies row conditional formatting from `FINAL DECISION`.
- Applies dropdowns and data type validation.
- Sends decision and stale-order email notifications.
- Builds a lightweight dashboard tab.
- Protects bot-owned columns from manual edits.
- Uses a spreadsheet-managed `Staff` tab for notification recipients and
  optional column permissions.

The bot still writes order rows and media links. This Apps Script is for sheet
UX, validation, notifications, and reporting inside Google Sheets.

## Installation

1. Open the live Order Approval Google Sheet.
2. Go to `Extensions > Apps Script`.
3. Create or replace the script file with the contents of:
   `order_approval_apps_script.gs`
4. Save the project.
5. Reload the Google Sheet.
6. Use the new `Orders` menu.
7. Run `Orders > Create/update Staff tab`.
8. Replace the sample staff rows with real staff names and emails.
9. Run `Orders > Apply validation + formatting`.
10. Add your Branch, County, Visited By, and HB Staff options in the
   `Dropdown Options` tab.
11. Optional: fill `Editable Columns`, add the Render Google service account as
   an active `IT` row with `Editable Columns=All`, then run
   `Orders > Apply Staff permissions`.
12. Run `Orders > Install daily triggers`.

Google will ask for permissions the first time menu actions send emails,
create triggers, or modify protections.

## Required Sheet Structure

The script expects the main order tab to be named:

```text
Orders
```

It expects:

- Row 1: visual title banner
- Row 2: bot-compatible headers
- Row 3+: order rows

The script is aligned to the current generated template:

```text
ORDER RECORD ID | DATE VISITED | CUSTOMER NAME | BRANCH | ID NUMBER |
CONTACTS / PRIMARY | CONTACTS / SECONDARY | COUNTY |
LOCATION AND NEAREST LANDMARK | VISITED BY | HB STAFF | DEPOSIT / HB |
DEPOSIT / JBL | COMMENT | IS CUSTOMER CREATED ON IMAB? | CUSTOMER NO |
CREDIT ANALYSIS | FINAL DECISION | Media URLs
```

The main columns are defined in `CFG.C` inside the script. If the sheet layout
changes, update those column numbers before using the script.

## Staff Tab

The script reads notification recipients from a tab named:

```text
Staff
```

Run `Orders > Create/update Staff tab` to create it.

Columns:

| Column | Meaning |
|---|---|
| `Name` | Staff name. Used to match `VISITED BY` for BRO notifications. |
| `Email` | Email address to notify. |
| `Role` | `BRO`, `Manager`, `Back-office`, or `All`. |
| `Branch` | Branch name, or `All`. |
| `Notify On` | Comma-separated events. |
| `Editable Columns` | Optional comma-separated edit permission tokens. |
| `Active` | `Yes` to enable, `No` to disable. |

Supported `Notify On` values:

```text
decision_approved
decision_rejected
stale_digest
all
```

Example:

| Name | Email | Role | Branch | Notify On | Editable Columns | Active |
|---|---|---|---|---|---|---|
| Sam Manager | sam@example.com | Manager | All | decision_approved,decision_rejected,stale_digest | All | Yes |
| Jane BRO | jane@example.com | BRO | Muranga | decision_approved,decision_rejected,stale_digest | BRO | Yes |
| Render Bot Service Account | bot@example.iam.gserviceaccount.com | IT | All | all | All | Yes |

Supported `Editable Columns` values:

- `All` gives access to all order columns.
- `BRO`, `Back-office`, `Manager`, and `IT` expand to role-based column groups
  defined in `CFG.ROLE_EDIT_GROUPS`.
- Exact header names are supported, for example `DATE VISITED`.
- Column letters and numbers are supported, for example `F` or `18`.

If `Editable Columns` is blank for every active staff row, strict staff
permissions are not applied. This avoids accidentally locking everyone out.

Important: strict protections can block the Render bot from writing sheet
updates. If you run `Orders > Apply Staff permissions`, add the same Google
service account used by Render to `Staff` with `Active=Yes` and
`Editable Columns=All`.

## Notification Rules

### Final Decision

When `FINAL DECISION` is edited to `Approved` or `Rejected`, the script sends
an email to:

- active `Manager`, `Back-office`, or `All` staff matching the event and branch
- active `BRO` or `All` staff matching the event, branch, and `VISITED BY`

If no matching active staff rows exist, the script logs the missing recipient
case and does not send an email.

### Stale Digest

The daily stale scan finds rows with:

- customer name present
- no final decision
- `DATE VISITED` older than or equal to `CFG.STALE_DAYS`

It sends:

- one full digest to active `Manager`, `Back-office`, or `All` staff
- branch-level digests to active `BRO` staff for matching branches and
  `VISITED BY` names

## Menu Actions

The `Orders` menu contains:

| Menu item | Function | Purpose |
|---|---|---|
| Search by ID / Name / Phone | `showSearch` | Opens a search dialog. |
| Highlight pending decisions | `highlightPending` | Highlights rows with no final decision. |
| Highlight stale rows | `highlightStale` | Highlights rows pending for `CFG.STALE_DAYS` days. |
| Validate required fields | `validateRequired` | Reports rows missing required fields. |
| Apply validation + formatting | `applyOrderValidationAndFormatting` | Applies dropdowns, type validation, and final-decision row colours. |
| Repair media links | `repairMediaLinks` | Makes multiple URLs in `Media URLs` independently clickable. |
| Refresh dashboard | `buildDashboard` | Rebuilds the dashboard sheet. |
| Create/update Staff tab | `ensureStaffSheet` | Creates or repairs the Staff tab headers. |
| Protect bot columns | `protectBotCols` | Protects bot-managed columns. |
| Apply Staff permissions | `applyStaffPermissions` | Applies column edit protections from `Staff.Editable Columns`. |
| Install daily triggers | `installTriggers` | Installs stale scan and dashboard refresh triggers. |

## Function Reference

### Configuration

`CFG`

Main configuration object. Defines sheet names, header rows, column numbers,
bot-owned columns, required fields, colours, stale-day threshold, and Staff tab
metadata.

### Menu And Triggers

`onOpen()`

Builds the `Orders` menu whenever the spreadsheet is opened.

`installTriggers()`

Deletes existing project triggers, then installs:

- `dailyStaleScan` daily at 08:00
- `buildDashboard` hourly

### Edit Handling

`onEdit(e)`

Main edit hook for the `Orders` tab. It:

- fills missing `DATE VISITED`
- checks duplicate ID numbers
- normalises phone numbers
- title-cases customer names
- colours rows by final decision
- sends decision notifications

`autoDate(sh, row, editedCol)`

Sets `DATE VISITED` to today when a staff member first edits a data row.

`checkDuplicate(sh, row, newId)`

Warns when the same `ID NUMBER` exists in another row.

`normalisePhone(sh, row, col)`

Normalises manually typed Kenyan phone numbers.

`titleCase(sh, row, col)`

Converts customer names to Title Case.

`colourRow(sh, row)`

Applies row background and decision styling based on `FINAL DECISION`.

`refreshAllColours()`

Re-applies row colours to every data row.

### Validation And Highlighting

`validateRequired()`

Checks required columns and alerts staff about incomplete rows.

`applyOrderValidationAndFormatting()`

Creates/repairs the `Dropdown Options` tab, applies dropdown validation, applies
data type validation, and installs row conditional formatting based on
`FINAL DECISION`.

`ensureDropdownOptionsSheet()`

Creates the `Dropdown Options` tab. Staff manually maintain options under:
`Branch`, `County`, `Visited By`, and `HB Staff`.

`applyOrderDataValidation(sh, optionsSheet)`

Applies:

- dropdowns for `BRANCH`, `COUNTY`, `VISITED BY`, and `HB STAFF`
- strict dropdowns for IMAB, credit analysis, and final decision
- `254XXXXXXXXX` phone validation
- non-negative amount validation
- integer customer number validation
- date validation and `dd-mmm-yyyy` date formatting

Manual option dropdowns are warning-based so the bot is not blocked if a new
branch/staff value is submitted before the option list is updated.

`applyDecisionConditionalFormatting(sh)`

Highlights entire order rows from `FINAL DECISION`: approved, rejected, hold,
and under review.

`highlightPending()`

Highlights rows where a customer exists but `FINAL DECISION` is blank.

`highlightStale()`

Highlights rows with no final decision after `CFG.STALE_DAYS`.

`repairMediaLinks()`

Scans `Media URLs` and rewrites cells as rich text so each URL remains
clickable even when several links are stored in one cell.

### Staff Directory

`ensureStaffSheet()`

Creates or repairs the `Staff` tab and inserts inactive sample rows if empty.

`applyStaffPermissions()`

Reads active Staff rows and applies strict column protections based on
`Editable Columns`. Bot-managed columns remain warning-only.

`applyStaffSheetValidation(sh)`

Adds dropdown validation to Staff role, branch, and active-status columns.

`staffPermissionMap()`

Builds a column-to-editor-email map from active Staff rows.

`editableColumnsToIndexes(value, headers)`

Expands `Editable Columns` tokens into order-sheet column indexes.

`getStaffEmails(options)`

Reads the `Staff` tab and returns active emails matching:

- `event`
- `roles`
- `branch`
- optional `names`

`staffRoleMatches(value, roles)`

Checks whether a Staff row role matches the requested roles.

`staffBranchMatches(value, branch)`

Checks whether a Staff row branch matches a requested branch. `All` matches
every branch.

`staffEventMatches(value, event)`

Checks whether `Notify On` contains the requested event or `all`.

`staffNameMatches(value, names)`

Matches a Staff row name against parsed `VISITED BY` names.

`staffNameTokens(value)`

Splits `VISITED BY` values like `John & Kibinge` or `John and Kibinge` into
individual names.

`normalizeStaffToken(value)`

Normalises text for role, branch, event, and name matching.

`uniqueEmails(values)`

Deduplicates email addresses case-insensitively.

`isValidEmail(value)`

Basic email format validation.

### Notifications

`notifyDecision(sh, row, decision)`

Sends an email when `FINAL DECISION` becomes `Approved` or `Rejected`.

`dailyStaleScan()`

Triggered daily. Finds stale rows and calls `sendStaleDigest`.

`sendStaleDigest(rows)`

Routes stale digest emails to managers/back-office and branch BROs.

`sendStaleDigestEmail(recipients, rows, url)`

Formats and sends one stale digest email.

### Dashboard

`buildDashboard()`

Creates or refreshes the `Dashboard` tab with summary totals by decision,
branch, and month.

`_hdr(rng, bg, fg, sz)`

Small formatting helper for dashboard headers.

`_hdrRow(sh, row, labels, bg)`

Writes and formats a dashboard header row.

### Search

`showSearch()`

Opens a modal search dialog.

`runSearch(query)`

Searches rows by ID number, customer name, phone, secondary phone, or customer
number, then jumps to the first matching row.

## Operational Notes

- Keep Staff sample rows inactive until real emails are entered.
- Use exact branch names consistently between `Orders.BRANCH` and `Staff.Branch`.
- Use staff names in `VISITED BY` that can match the `Staff.Name` column.
- Use uppercase names in the sheet and form. The bot and Apps Script normalize
  customer name, branch, county, visited by, and HB staff to uppercase.
- Add the Render service account to Staff before applying strict staff
  permissions.
- If emails are not sent, check the Apps Script execution logs first.
- If the sheet layout changes, update `CFG.C` column numbers before enabling
  notifications.
