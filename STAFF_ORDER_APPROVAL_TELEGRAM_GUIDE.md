# Staff User Guide: Order Approval Workflow

This guide is for staff using a Telegram group configured for the order
approval workflow. The complaint/case workflow uses a different message format
and different commands.

The preferred method is the Telegram Web App form. Structured chat messages are
available as a fallback.

## Contents

- [Quick Start](#quick-start)
- [Create A New Order](#create-a-new-order)
- [Find And Edit An Existing Order](#find-and-edit-an-existing-order)
- [Required And Optional Fields](#required-and-optional-fields)
- [Data Validation And Formatting](#data-validation-and-formatting)
- [Uploading Media](#uploading-media)
- [Drive Folder And File Naming](#drive-folder-and-file-naming)
- [Success And Error Responses](#success-and-error-responses)
- [Structured Chat Fallback](#structured-chat-fallback)
- [Commands](#commands)
- [Troubleshooting](#troubleshooting)
- [Staff Safety Checklist](#staff-safety-checklist)

## Quick Start

In the order approval Telegram group, tag the bot and send:

```text
@<bot_username> /order
```

You can also use:

```text
@<bot_username> /form
```

Tap **Open Order Approval Form** in the bot response.

Use the actual bot username shown in your Telegram group. The deployment may
use a different username from examples in older documents.

## What The Form Supports

The form can:

- Create a new order row when the ID number does not exist.
- Find an existing order by ID number.
- Suggest possible IDs after the first three digits are entered.
- Load and edit an existing row.
- Clear existing values when a loaded field is intentionally left blank.
- Validate data before sending it to Google Sheets.
- Upload multiple ID photos, LAF documents, and other supporting files.
- Reuse an existing Drive upload when the exact same file is uploaded again.
- Show success or error details at the top of the form.
- Send a structured success or failure response to the Telegram group.

## Create A New Order

1. Open the form with `/order` or `/form`.
2. Enter the customer's full ID number.
3. Wait briefly for ID suggestions.
4. If no existing record is shown, complete the required details.
5. Select any supporting files.
6. Tap **Submit update**.
7. Confirm that both the form and Telegram group report success.

If the ID does not exist, the bot creates a row in the configured creation
worksheet.

When the sheet contains an `ORDER RECORD ID` column, the bot assigns the next
sequential reference, for example:

```text
JBL-1
JBL-2
JBL-3
```

This reference is bot-managed. Staff should not type, change, or reuse it.

## Find And Edit An Existing Order

1. Start typing the customer's ID number.
2. After at least three digits, review the suggested matches.
3. Tap the correct suggestion, or enter the full ID and tap **Load existing**.
4. Confirm that the form says the existing row was loaded.
5. Review all loaded values.
6. Make the required changes.
7. Submit the form.

Do not edit a record until it has been loaded. Loading establishes the exact
entry and a fingerprint of its current values.

### Blank Fields During Editing

The form is a true entry editor:

- For a newly created record, blank optional fields remain blank.
- For a loaded existing record, a blank field clears the corresponding value
  in Google Sheets.

Before submitting an edit, review the entire loaded form. Leave a field blank
only when its existing sheet value should be removed.

### Concurrent Or Stale Edits

If another person changes the entry after you load it, the bot can reject your
submission with:

```text
Reload this customer ID before saving. The entry changed after it was opened.
```

Load the ID again, review the latest values, reapply your changes, and submit.
This prevents an older form from silently overwriting newer work.

## Required And Optional Fields

The only technically mandatory field is:

- `ID number`

All other fields are optional at form validation level. Operational policy may
still require staff to complete specific fields before an approval is treated
as complete.

Customer fields:

- `ID number`
- `Date visited`
- `Customer name`
- `Branch`
- `Primary phone`
- `Secondary phone`

Visit fields:

- `County`
- `Sub-county`
- `Visited by`
- `HB staff`
- `IMAB created`
- `Landmark`

Approval fields:

- `HB deposit`
- `JBL deposit`
- `Customer no`
- `Credit analysis`
- `Final decision`
- `Comment`

File fields:

- `ID photos`
- `LAF document`
- `Other files`

## Data Validation And Formatting

The browser validates the form before submission. The server validates it again
before writing to Google Sheets.

### ID Number

The ID is the business key used to find, create, update, audit, and store media
for an order. Verify it carefully before submitting.

Duplicate entries with the same ID are rejected. Contact an administrator to
resolve them before trying again.

### Date Visited

Use the date picker. The bot writes the preferred sheet format:

```text
25-May-2026
```

### Phone Numbers

Phone numbers are stored in Kenyan `254` format:

```text
254740614990
```

The form converts these common inputs when possible:

```text
0740614990
740614990
+254740614990
254740614990
```

A valid stored number must be `254` followed by nine digits. Invalid phone
numbers are rejected before the sheet is updated.

### Names And Locations

The following values are trimmed, have repeated spaces removed, and are written
in uppercase:

- Customer name
- Branch
- County
- Sub-county
- Visited by
- HB staff

### Deposits

`HB deposit` and `JBL deposit` must:

- Be zero or greater.
- Contain numbers only, with an optional decimal point.
- Use no more than two decimal places.

Valid examples:

```text
0
5000
5000.50
```

### Customer Number

`Customer no` accepts digits only.

### Dropdown Values

`IMAB created`:

```text
Yes
No
Pending
```

`Credit analysis`:

```text
Approved
Pending
Rejected
```

`Final decision`:

```text
Approved
Rejected
Deferred
Under Review
```

`Branch` is a form dropdown controlled by the deployment configuration. Use the
standard branch shown in the list. Ask an administrator if the required branch
is missing.

At present, `County`, `Sub-county`, `Visited by`, and `HB staff` are text fields in the Web
App even if Google Sheets has dropdown validation for those columns. Sheet
dropdown options do not automatically populate the Web App.

## Uploading Media

The form provides three upload slots.

### ID Photos

Use for one or more ID images. The phone file picker is restricted to images.

### LAF Document

Use for one or more LAF pages or documents. The picker accepts:

- Images
- PDF
- DOC
- DOCX

### Other Files

Use for other supporting evidence. The picker accepts:

- Images
- PDF
- DOC
- DOCX
- XLS
- XLSX

### Upload Limits

The form displays the configured maximum size per file. Production defaults
are normally:

- Maximum per file: `20 MB`
- Maximum files per slot: `10`
- Maximum total for one submission: configured by the deployment, commonly
  `30 MB` or `60 MB`

The current deployment values are authoritative. Use `/health` to see the
configured maximum file size and maximum total upload size.

- Too many files in a slot reject the submission.
- A total upload above the configured limit rejects the submission.
- An individual oversized file is normally blocked by the form. If it reaches
  the server, the bot can skip that file, save the remaining valid work, and
  report a warning.

Read the form and Telegram response before retrying so that successfully stored
files are not selected again unnecessarily.

### Phone Memory And Image Previews

On phones, the form automatically uses phone-safe upload mode:

- It does not decode image thumbnails.
- Each upload slot accepts up to two files per submission.
- Additional files can be submitted later using the same customer ID.

When opened inside Telegram, tap **Use phone browser** if the embedded form
still reports low memory. It opens the same signed form in the phone's normal
browser.

Desktop browsers can retain multi-file selection and optional thumbnails.
Large photos can consume much more memory when decoded than their saved file
size.

If the phone reports low memory:

1. Close other apps or browser tabs.
2. Do not open thumbnails.
3. Select fewer files.
4. Upload documents first.
5. Reopen the same ID and upload photos in smaller batches.

Uploading another batch to an existing ID updates the same order and uses the
same Drive ID folder.

## Drive Folder And File Naming

All media for the same ID is stored in one ID folder:

```text
<configured media root>/
  <Telegram group name>/
    2026/
      May/
        ID_113650221/
```

Names start with the date so files sort chronologically:

```text
2026-05-09 KYC ID-113650221 01.jpg
2026-05-09 LAF Biogas ID-113650221 01.pdf
2026-05-09 FILE Biogas ID-113650221 01.pdf
```

The bot does not use `p1` or `p2`, because it cannot reliably determine whether
several uploads are pages of one document or separate documents.

See [ORDER_APPROVAL_MEDIA_NAMING.md](ORDER_APPROVAL_MEDIA_NAMING.md) for the
full naming policy.

### Duplicate Media

If the same ID receives the exact same web file again, with matching file
details and content hash, the bot reuses the existing Drive file and link.

A changed file, even with the same original filename, is treated as a new file
and receives the next sequence number.

## Success And Error Responses

After every form submission:

- The form shows a success or error message at the top of the screen.
- The bot sends a response to the Telegram group.

A successful response identifies:

- Whether the entry was created or updated.
- The stable order record ID, such as `JBL-7`.
- The customer ID.
- The customer name when available.
- The number of files stored.
- Only fields that were actually added, updated, cleared, or appended.
- Any upload warnings.

Example:

```text
ENTRY UPDATED

Order record ID: JBL-7
Customer ID: 113650221
Customer: PATRICK MWANGI MAINA
Files stored: 2

Updated fields
- CUSTOMER NAME: updated
- CONTACTS / PRIMARY: updated
- Media URLs: appended
```

The response intentionally does not show worksheet names, row numbers, or
column letters. Those are internal implementation details used only for audit
and safe matching.

An error response includes a **Fix** section. Correct every listed problem
before resubmitting.

Do not assume a save succeeded merely because the form closed. Confirm the
Telegram success response.

## Structured Chat Fallback

The form is recommended. When it cannot be used, send one tagged structured
message:

```text
@<bot_username>
ID: 113650221
DATE VISITED: 25-May-2026
CUSTOMER NAME: PATRICK MWANGI MAINA
BRANCH: MURANGA
PRIMARY PHONE: 254740614990
SECONDARY PHONE:
COUNTY: MURANGA
SUB-COUNTY: KIHARU
LANDMARK: GITURI NEAR KAGANDA CENTRE
VISITED BY: JOHN
HB STAFF: THOMAS
HB DEPOSIT: 5000
JBL DEPOSIT: 0
COMMENT: APPROVED
IMAB CREATED: YES
CUSTOMER NO: 15118
CREDIT ANALYSIS: PENDING
FINAL DECISION: UNDER REVIEW
```

Rules:

- Include an `ID:` line.
- Use the supported labels exactly.
- Phone numbers are normalized and validated.
- Invalid decision values, amounts, dates, phone numbers, or customer numbers
  reject the update.
- Unknown labels are ignored and reported as warnings.
- Fields omitted from a chat update are not cleared.
- If no matching ID exists, the structured message creates a new row.
- If more than one matching ID exists, no row is updated.

This differs from the loaded Web App editor, where blank loaded fields can clear
existing values.

## Follow-Up Media In Telegram

When an order was submitted as a structured Telegram message, send follow-up
photos or documents as a reply to that original update message. The bot uses
the reply relationship to recover the ID and append the media links.

Do not send unlabelled media as a new unrelated group message. The bot may not
know which order should receive it.

For normal use, reopening the Web App and uploading against the same ID is
clearer and provides separate file categories.

## Commands

Commands shown by Telegram are specific to the workflow configured for the
group.

### `/order`

```text
@<bot_username> /order
```

Opens the order approval form.

### `/form`

```text
@<bot_username> /form
```

Alias for `/order`.

### `/group`

```text
@<bot_username> /group
```

Shows whether the current Telegram group is enabled and how it is routed. Use
it when the bot appears to be using the wrong workflow or sheet.

### `/health`

```text
@<bot_username> /health
```

Shows operational diagnostics, including:

- Database and group configuration status.
- Enabled state and workflow type.
- Whether a sheet is configured.
- Order update and media counts.
- Pending or failed updates and uploads.
- Configured order tabs and header row.
- Media provider and upload limits.
- Whether image previews are enabled.
- Whether required runtime settings are present.

`/health` confirms configuration and audit status. It does not perform a full
write test against Google Sheets or Google Drive.

### `/help`

```text
@<bot_username> /help
```

Lists only the commands available for the current group's workflow.

## Troubleshooting

### The bot does not reply

1. Confirm that the bot was tagged.
2. Send `@<bot_username> /group`.
3. Confirm the bot is still a group member.
4. Ask an administrator to verify the current group ID and enabled state.

If Telegram upgraded the group to a supergroup, its group ID may have changed
to a value beginning with `-100`.

### The form does not open

- Send `/order` again instead of reusing an old button.
- Confirm mobile data or Wi-Fi is working.
- Run `/health` and check that the base URL and group are configured.
- If the page says the form is unavailable, contact an administrator.

### The form token expired or is invalid

Close the old form and send:

```text
@<bot_username> /order
```

Use the new button. Do not reuse an old copied form URL.

### No existing order is found

Check:

- The ID was typed correctly.
- The ID is in the sheet's `ID NUMBER` column.
- The row is in a worksheet configured for the order workflow.
- The sheet's configured header row is correct.

If the ID genuinely does not exist, submitting creates a new row.

### Duplicate entries are found

The bot does not choose between duplicates. Ask an administrator to merge or
remove the duplicate entries, then load the ID again.

Files selected during the failed duplicate attempt may already have been
stored. Read the Telegram response before uploading them again.

### Validation fails

Read the complete message at the top of the form. It lists every detected
problem. Typical causes are:

- Missing ID.
- Phone number not convertible to `254XXXXXXXXX`.
- Negative or malformed deposit.
- Customer number containing non-digits.
- Unsupported decision value in structured chat.
- Too many files.
- One file exceeding the per-file limit.
- Total upload exceeding the submission limit.

### The entry changed before saving

Load the ID again and repeat the edit against the latest values.

### Upload fails

- Keep the form open and read any warning.
- Reduce the file count or total size.
- Retry with one slot at a time.
- Avoid thumbnails on low-memory phones.
- Run `/health` and report any failed or pending media count to an
  administrator.

### The sheet changed but a file failed

The Telegram response lists stored file count and warnings separately. A field
update can succeed while an individual file is skipped. Retry only the failed
file against the same ID.

### A branch is missing

Do not type a non-standard substitute. Ask an administrator to update the
configured branch choices and keep them aligned with the Google Sheet
validation list.

## Staff Safety Checklist

Before submission:

- Confirm the customer ID.
- Confirm the correct existing match was loaded.
- Review all loaded fields before clearing blanks.
- Use the standardized branch.
- Check phone numbers.
- Check decision dropdowns.
- Keep uploads within the displayed limits.

After submission:

- Read the form result.
- Confirm the Telegram group response.
- Review warnings and file count.
- Correct and resubmit any listed error.

## Administrator References

Staff do not need these documents for daily data entry:

- [ORDER_APPROVAL_RENDER_DEPLOYMENT.md](ORDER_APPROVAL_RENDER_DEPLOYMENT.md) -
  Render, Telegram, Google Sheet, and group configuration.
- [MULTI_GROUP_WORKFLOW_CONFIGURATION.md](MULTI_GROUP_WORKFLOW_CONFIGURATION.md)
  - workflow presets and group routing.
- [ORDER_APPROVAL_MEDIA_NAMING.md](ORDER_APPROVAL_MEDIA_NAMING.md) - Drive
  directory and filename policy.
- [ORDER_APPROVAL_APPS_SCRIPT.md](ORDER_APPROVAL_APPS_SCRIPT.md) - spreadsheet
  Apps Script setup and alerts.
