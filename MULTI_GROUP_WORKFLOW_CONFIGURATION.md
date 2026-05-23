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

## Order Approval Workflow

Use a separate Telegram group for the live order approval Google Sheet. In that group's admin configuration, set `workflow` to:

```json
{
  "type": "order_approval",
  "match_field": "id_number",
  "search_sheet_names": ["Pending", "178", "179", "180", "181"],
  "media_field": "media_urls"
}
```

The workflow expects structured labels such as `ID:`, `DATE VISITED:`, `CUSTOMER NAME:`, `PRIMARY PHONE:`, `HB DEPOSIT:`, and `CREDIT ANALYSIS:`. It searches the configured tabs by the `ID NUMBER` column, updates only the BRO fields that were supplied, and appends uploaded Google Drive links to the existing `Media URLs` cell.

Each searched worksheet must already contain a `Media URLs` header. The bot does not add columns to the approval workbook.

Media storage uses these environment settings:

```text
MEDIA_STORAGE_PROVIDER=google_drive
MEDIA_MAX_FILE_SIZE_MB=20
GOOGLE_DRIVE_MEDIA_FOLDER_ID=<drive-folder-id>
```

Photos and documents are stored under `year/month/ID_<id-number>/` in the configured Drive folder. Follow-up photos or documents can be sent as replies to the original order update message, and the bot will append their Drive links to the same approval row.

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
