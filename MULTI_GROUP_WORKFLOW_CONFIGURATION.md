# Multi-Group Spreadsheet and Workflow Configuration

The bot supports different Telegram groups writing to different spreadsheets, worksheet tabs, and sheet layouts.

The Django database remains canonical internally, but each group can map those canonical case fields to its own spreadsheet headers.

For simple setup, use workflow presets in Django admin. See `WORKFLOW_PRESETS.md`.

## Default Behavior

If no per-group schema is configured, the bot uses the current biogas complaint-register layout:

```text
Complaint ID | message_id | Date Reported | Customer Name | Customer ID / Account
Phone Number | JBL Reported By | Branch / Region | Complaint Category
Complaint Description | raw_message | gps_link | image_flag | source
Loan Status | Loan at Risk | Risk Level | Status | Resolution Details
Date Resolved | Days Open
```

This preserves the current workflow.

## Per-Group Configuration

The preferred way to configure groups is through Django admin:

1. Open Django admin.
2. Go to `Core` -> `Group sheet configurations`.
3. Add or edit a group configuration.
4. Set:
   - `group_id`: Telegram group chat ID, for example `-1001234567890`
   - `sheet_id`: Google spreadsheet ID
   - `sheet_name`: worksheet/tab name
   - `sheet_schema`: optional column mapping JSON
   - `workflow`: optional workflow/dropdown JSON
   - `parser_rules`: optional per-group parser JSON
5. Save the configuration.

Admin-managed configuration overrides `GROUP_MAPPING_JSON` for the same group ID. Environment variables remain useful for bootstrap and deployments where admin-managed config is not wanted.

## Viewing Sheet-Specific Data In Django Admin

The Django admin exposes the backend tables used by each workflow:

- `Parsed messages` contains complaint/case records mirrored between Telegram, Django, and Google Sheets.
- `Order approval updates` contains the audit history of order approval form and Telegram updates.
- `Media attachments` contains the upload audit history and Drive links.
- `Case updates` contains complaint status and resolution update history.

To avoid mixing data from different groups or spreadsheets:

1. Open Django admin.
2. Go to `Core` -> `Group sheet configurations`.
3. Find the Telegram group or sheet you want to inspect.
4. Click `Open live sheet records` to view the actual worksheet headers and row values.
5. Select a worksheet tab where the workflow has more than one configured tab.
6. Click `Edit` beside a row to change its live Google Sheet values.
7. Use the separate confirmation checkbox before permanently deleting a live sheet row.
8. Click `View complaint cases` for a case workflow, or `View order update audit` for an order approval workflow, to inspect backend records.
9. Click `View media audit` to inspect uploads from that group.

These links open the relevant Django table with filters for that configured group and spreadsheet. The standard filters on each table can further separate records by spreadsheet ID, worksheet tab, sync status, or date.

The live sheet records page uses the configured `workflow.header_row` for every workflow, then displays columns in the same order as that Google Sheet header row. It does not assume headers are on row 1. Formula cells and system tracking identifiers such as complaint `message_id` and order `ORDER RECORD ID` are read-only. Successful complaint row edits and deletes refresh the Django complaint mirror from the sheet. Existing mirror and audit tables are read-only in Django admin so they cannot be changed without updating the live sheet.

For order approval workflows, the Google Sheet remains the complete current order table. Django stores the update audit records and media audit records rather than a full duplicate of every current sheet row.

## Order Approval Workflow

Use a separate Telegram group for the live order approval Google Sheet. In that group's admin configuration, set `workflow` to:

```json
{
  "type": "order_approval",
  "match_field": "id_number",
  "search_sheet_names": ["Orders"],
  "create_sheet_name": "Orders",
  "media_field": "media_urls",
  "header_row": 2
}
```

The workflow expects structured labels such as `ID:`, `DATE VISITED:`, `CUSTOMER NAME:`, `BRANCH:`, `PRIMARY PHONE:`, `HB DEPOSIT:`, `CREDIT ANALYSIS:`, and `FINAL DECISION:`. It searches the configured `Orders` tab by the `ID NUMBER` column, updates only the fields that were supplied, and appends uploaded Google Drive links to the existing `Media URLs` cell. `DATE VISITED` is written back as `DD-Mon-YYYY`, for example `25-May-2026`.

The `Orders` worksheet must already contain `ID NUMBER` and `Media URLs` headers on row 2. Row 1 can be a visual title. The bot does not add columns to the approval workbook.

Media storage uses these environment settings:

```text
MEDIA_STORAGE_PROVIDER=google_drive
MEDIA_MAX_FILE_SIZE_MB=20
GOOGLE_DRIVE_MEDIA_FOLDER_ID=<drive-folder-id>
```

Photos and documents are stored under `year/month/ID_<id-number>/` in the configured Drive folder. Follow-up photos or documents can be sent as replies to the original order update message, and the bot will append their Drive links to the same approval row.

## Jawabu HomeBiogas Workflow

Use the `Jawabu HomeBiogas` preset for the group that imports Jawabu WhatsApp visits and Farmers CSV exports. The ordinary group `sheet_name` can remain `Jawabu Visits` for WhatsApp `/batch` imports. Farmers CSV `/farmup` commits can optionally write reviewed rows into a separate Master Data tab/workbook.

Recommended workflow JSON when Master Data sync is enabled:

```json
{
  "type": "jawabu_homebiogas",
  "header_row": 1,
  "import_start_date": "2026-05-01",
  "duplicate_key_fields": ["national_id", "primary_phone"],
  "duplicate_policy": "flag_for_review",
  "master_sync_enabled": true,
  "master_sheet_id": "",
  "master_sheet_name": "Master Data",
  "master_header_row": 3,
  "master_data_start_row": 5,
  "master_import_log_sheet_name": "Farmers Upload Log"
}
```

Leave `master_sheet_id` blank when the same spreadsheet configured on the group contains the `Master Data` tab. Set it only when Master Data lives in a different spreadsheet. The service account used by Render needs edit access to that spreadsheet.

The Master Data sheet reserves hidden far-right system columns from `AS` onward:

```text
Master Record ID | Import Batch ID | Source Filename | Source Row | Duplicate Key
Import Status | Review Notes | Reviewed By | Reviewed At | Last Updated At
```

Do not place staff-facing columns after those system columns. Add future staff columns before the visible audit area, or deliberately move the system block further right and update the script/config together.

## Sheet Analyzer

For a new group or a new spreadsheet layout, use the built-in Google Sheet analyzer instead of writing `sheet_schema` manually.

### How To Analyze A Sheet

1. In Django admin, open `Core` -> `Group sheet configurations`.
2. Create or open a saved group configuration.
3. Enter the live Google `sheet_id` and `sheet_name`.
4. Save the configuration.
5. Click `Analyze columns and dropdowns`.
6. Review the detected columns, sample values, dropdown values, data types, formula columns, and suggested canonical field mappings.
7. Click `Apply detected schema` if the preview is correct.

The analyzer reads the live Google Sheet by spreadsheet ID and tab name. It does not require uploading an `.xlsx` file.

### What It Extracts

- Header row columns.
- Sample values from the first rows.
- Likely data types such as text, date, phone, number, boolean, URL, empty, or dropdown.
- Formula columns, using formula-rendered sheet values.
- Google Sheets dropdown/data-validation values, when Sheets API v4 metadata is available.
- Suggested canonical field mappings.
- Suggested `sheet_schema`.
- Suggested workflow dropdown metadata.

### What Gets Saved

When you click `Apply detected schema`, the system updates:

- `sheet_schema`: generated mapping from canonical backend fields to this sheet's headers.
- `workflow.dropdown_values`: detected dropdown values by canonical field, such as `status`.
- `metadata.sheet_analysis`: analysis snapshot with columns, sample size, warnings, and timestamp.

The analyzer does not write case data into the sheet. It only reads the sheet and updates the group configuration in the backend.

### Review Warnings

The analyzer is heuristic. Review the preview before applying, especially when headers are ambiguous. For example, `Name`, `Client`, `Customer`, and `Reported By` can be confused depending on the spreadsheet.

Warnings are shown when:

- Duplicate headers are detected.
- Important fields such as `message_id`, `customer_name`, `customer_phone`, or `complaint_description` are not confidently mapped.
- The sheet is empty or inaccessible.

If the mapping is not correct, edit `sheet_schema` manually after applying, or adjust the spreadsheet headers and run the analyzer again.

### Access Requirements

The configured Google service account must have access to the spreadsheet. Dropdown extraction also requires the Google Sheets API v4 support that the project already initializes through `googleapiclient`.

## Environment JSON Configuration

Use `GROUP_MAPPING_JSON` to configure each Telegram group.

Example:

```json
{
  "-1001111111111": {
    "sheet_id": "spreadsheet_id_for_biogas_cases",
    "sheet_name": "Complaints Register"
  },
  "-1002222222222": {
    "sheet_id": "spreadsheet_id_for_support_cases",
    "sheet_name": "Support",
    "sheet_schema": {
      "columns": [
        "Ticket No",
        "Backend ID",
        "Reported On",
        "Client",
        "Account",
        "Mobile",
        "Reported By",
        "Issue",
        "Case State",
        "Fix Notes"
      ],
      "field_headers": {
        "complaint_id": "Ticket No",
        "message_id": "Backend ID",
        "date_reported": "Reported On",
        "customer_name": "Client",
        "customer_id": "Account",
        "customer_phone": "Mobile",
        "reported_by": "Reported By",
        "complaint_description": "Issue",
        "status": "Case State",
        "resolution_details": "Fix Notes"
      },
      "formula_fields": ["complaint_id"],
      "bot_writable_fields": [
        "message_id",
        "date_reported",
        "customer_name",
        "customer_id",
        "customer_phone",
        "reported_by",
        "complaint_description"
      ],
      "case_update_fields": [
        "status",
        "resolution_details"
      ]
    }
  }
}
```

## Canonical Field Names

Use these field names in `field_headers`, `bot_writable_fields`, `formula_fields`, and `case_update_fields`:

```text
complaint_id
message_id
date_reported
customer_name
customer_id
customer_phone
reported_by
branch_region
complaint_category
complaint_description
raw_message
gps_link
image_flag
source
loan_status
loan_at_risk
risk_level
status
resolution_details
date_resolved
days_open
```

## Safety Rules

- Formula fields are never written by the bot.
- Bot intake writes only fields listed in `bot_writable_fields`.
- Status updates write only fields listed in `case_update_fields`.
- Rows are still found by the configured `message_id` header.
- Sheet-to-backend sync uses the same configured headers, so renamed columns can still sync back into the database.

## Notes

The parser still produces the same canonical case fields in the database. The per-group schema controls how those fields appear in each spreadsheet.

For completely different message formats or non-case workflows, add a separate parser/workflow implementation and reference it from the group configuration.
