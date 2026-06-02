# Complaint Management Register Setup

This setup matches the Order Approval workbook pattern while keeping the
existing case/complaint bot workflow compatible.

## Files

- `Complaint_Management_Register_V2.xlsx`
  Redesigned complaint workbook generated from `COMPLAINT MANAGEMENT REGISTER(1).xlsx`.
- `scripts/create_complaint_register_workbook.py`
  Rebuilds the workbook from the current complaint register.
- `complaint_management_apps_script.gs`
  Google Apps Script for validation, dashboard, Staff permissions, alerts, and
  owner/IT-only menu actions.

## Workbook Structure

`Complaints Register`

- Row 1: visual title banner.
- Row 2: bot-readable headers.
- Row 3+: complaint rows.

Required bot headers on row 2:

```text
Complaint ID
message_id
Date Reported
Customer Name
Customer ID / Account
Phone Number
JBL Reported By
Branch / Region
Complaint Category
Complaint Description
raw_message
gps_link
image_flag
source
Loan Status
Loan at Risk
Risk Level
Status
Resolution Details
Date Resolved
Days Open
```

Extra tabs:

- `Complaint Summary`: dashboard formulas.
- `Dropdown Options`: editable dropdown source lists.
- `Staff`: emails, roles, notifications, and permissions.
- `Legend`: column ownership and setup notes.

## Rebuild The Excel File

From `biogas_bot`:

```text
python scripts/create_complaint_register_workbook.py -i "COMPLAINT MANAGEMENT REGISTER(1).xlsx" -o "Complaint_Management_Register_V2.xlsx"
```

Blank template:

```text
python scripts/create_complaint_register_workbook.py --blank -o "Complaint_Management_Register_Template.xlsx"
```

## Django Admin Group Setup

For the cases Telegram group:

```text
enabled: checked
group_id: -100...
display_name: Complaints
sheet_id: <new Google Sheet ID>
sheet_name: Complaints Register
workflow_preset: Case / Complaints
```

The preset generates:

```json
{
  "type": "case",
  "header_row": 2
}
```

This is required because the new workbook uses row 1 as a title and row 2 as
the real header row.

## Apps Script Setup

1. Upload `Complaint_Management_Register_V2.xlsx` to Google Drive and open it as
   a Google Sheet.
2. Open `Extensions -> Apps Script`.
3. Paste `complaint_management_apps_script.gs`.
4. Save.
5. Run `setupComplaintRegisterSupport()` once and authorize.
6. Replace sample rows in `Staff` with real staff emails.
7. Add the Render Google service account to `Staff` with:

```text
Role: IT
Editable Columns: All
Active: Yes
```

8. Use the `Complaints` menu to run:

```text
Apply validation + formatting
Validate Staff tab
Apply Staff permissions
Install daily triggers
```

## Staff Tab

Columns:

```text
Name | Email | Role | Branch | Notify On | Editable Columns | Active
```

Role examples:

```text
IT
Manager
Support
BRO
All
```

Notify On examples:

```text
all
stale_digest
status_resolved
status_closed
```

Editable Columns examples:

```text
All
Risk
Resolution
Status
Resolution Details
Date Resolved
```

The custom `Complaints` menu is visible only to the sheet owner or active Staff
rows with role `IT` or `All`.

## Useful Menu Actions

- `Search complaints`
- `Apply validation + formatting`
- `Validate required fields`
- `Highlight stale open cases`
- `Refresh dashboard`
- `Send stale digest now`
- `Send status alert for selected row`
- `Protect bot columns`
- `Apply Staff permissions`
- `Install daily triggers`

## Validation And Formatting

The workbook includes:

- Status, category, branch, reporter, loan status, risk, source, and image flag
  dropdowns.
- Phone validation for `254XXXXXXXXX`.
- Date validation for reported/resolved dates.
- Non-negative validation for `Loan at Risk`.
- Uppercase validation for customer/reporter/branch names.
- Conditional row highlighting by `Status` and `Risk Level`.

## Production Note

After the new Google Sheet is confirmed:

- Keep the cases group explicitly configured in Django Admin.
- Use `Case / Complaints`.
- Remove old cases group routing from `GROUP_MAPPING_JSON` if it is still set.
- Keep the old workbook as a backup until `/group`, `/health`, and a test
  complaint message confirm the new sheet is receiving rows.
