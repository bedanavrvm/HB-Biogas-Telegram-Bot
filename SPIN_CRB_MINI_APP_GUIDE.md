# SPIN/CRB Mini App Guide

This guide documents the SPIN/CRB workflow, Mini App form, media uploads, sheet requirements, and Render/BotFather configuration.

## Workflow Purpose

The SPIN/CRB workflow captures requests from BROs for:

- SPIN/CRB, the usual request where the analyst pulls both reports and produces the credit analysis output
- SPIN only, for rare single-report requests
- CRB only, for rare single-report requests

Credit analysis is not a request type. It is the later output/status produced by the analyst after SPIN/CRB report work and should be tracked in the `Analysis Status` / `Analyst Response` columns.

## Telegram Commands

Use these commands only in a Telegram group configured with workflow type `spin_credit_analysis`:

- `@hb_biogas_cases_bot /spin` - opens the SPIN/CRB Mini App form.
- `@hb_biogas_cases_bot /form` - opens the same Mini App form.
- `@hb_biogas_cases_bot /batch` - imports supported WhatsApp chat exports for SPIN/CRB requests.

## Mini App URL

Configure this URL in BotFather for the SPIN/CRB Mini App:

```text
https://jbl-biogas-telegram-bot.onrender.com/spin/
```

Then set the Render environment variable:

```text
SPIN_MINI_APP_SHORT_NAME=<botfather-mini-app-short-name>
```

If `SPIN_MINI_APP_SHORT_NAME` is not set, the bot falls back to a signed web link using `APP_BASE_URL`.

## Required Render Environment Variables

Core Mini App settings:

```text
APP_BASE_URL=https://jbl-biogas-telegram-bot.onrender.com
SPIN_MINI_APP_SHORT_NAME=<botfather-mini-app-short-name>
SPIN_WEBAPP_REQUIRE_TELEGRAM_AUTH=True
SPIN_WEBAPP_AUTH_MAX_AGE_SECONDS=86400
```

Media upload settings:

```text
GOOGLE_DRIVE_MEDIA_FOLDER_ID=<drive-root-folder-id>
MEDIA_STORAGE_PROVIDER=google_drive
MEDIA_MAX_FILE_SIZE_MB=20
SPIN_MAX_FILES_PER_SLOT=2
SPIN_MAX_TOTAL_UPLOAD_MB=20
```

`SPIN_MAX_FILES_PER_SLOT` defaults to `2`. `SPIN_MAX_TOTAL_UPLOAD_MB` defaults to `20`.

## Sheet Requirements

The configured SPIN/CRB worksheet should include these headers:

```text
Request ID
Request Date/Time
Branch
Requested By
Request Type
Customer Name
National ID
Raw ID Text
Primary Phone
Secondary Phone
Customer Type
Loan Product
Requested Amount
Tenor
Business / Employment Notes
MPESA Statement Code
Attachments
Media URLs
Raw Message
Source Chat
Source Filename
Source Message Hash
Parse Status
Missing Fields
Analysis Status
Analyst Response
```

`Media URLs` is required when files are uploaded. If a user submits files and the column is missing, the request is rejected with a clear error instead of silently losing Drive links.

## Mini App Fields

The form captures:

- Request Type: `SPIN/CRB`, `SPIN`, or `CRB`
- Customer Name
- National ID
- Primary Phone, normalized to `254...`
- Secondary Phone, optional and normalized to `254...`
- Customer Type: New / Existing / blank
- Requested Amount
- Tenor
- Loan Product
- MPESA Statement Code
- Business / Employment Notes

## Upload Slots

The Mini App supports three upload slots:

- `ID Photos` -> stored as `id_photo`
- `LAF Documents` -> stored as `laf_doc`
- `Other Files` -> stored as `other_file`

Each slot accepts up to 2 files by default. The total upload size is capped by `SPIN_MAX_TOTAL_UPLOAD_MB`.

## Drive Storage Behavior

Uploads reuse the existing Google Drive media storage flow used by the order workflow.

Folder structure follows:

```text
<GOOGLE_DRIVE_MEDIA_FOLDER_ID>/
└── <Telegram group display name or media_root_folder>/
    └── 2026/
        └── July/
            └── ID_<National ID>/
                ├── 2026-07-11 KYC ID-12345678 01.jpg
                ├── 2026-07-11 LAF Biogas ID-12345678 01.pdf
                └── 2026-07-11 FILE Biogas ID-12345678 01.pdf
```

The date is first in the filename for sorting.

Duplicate uploads are detected by content hash, group, customer ID, file type, original filename, and size. If the same file is uploaded again, the existing Drive URL is reused.

## Sheet Write Behavior

On successful Mini App submit:

- The DB audit record is created.
- Uploaded files are stored in Drive.
- Original uploaded filenames are written to `Attachments`.
- Drive links are written to `Media URLs`.
- The final request row is appended to the configured SPIN/CRB sheet.
- The bot replies in the Telegram group with request ID, type, customer, ID, phone, and files stored.

If media upload or sheet sync fails, the form returns an error and the bot does not report success.

## WhatsApp Batch Import Notes

`/batch` is for legacy WhatsApp exports only. It writes to the same configured workbook ID as the SPIN group, but to a separate worksheet tab so imported historical chats do not mix with live Mini App requests.

Default legacy tab name:

```text
SPIN Legacy Batch
```

You can override it in the workflow JSON:

```json
{
  "type": "spin_credit_analysis",
  "header_row": 1,
  "legacy_batch_sheet_name": "SPIN Legacy Batch"
}
```

The legacy tab should contain the same headers as the live SPIN tab. `Analysis Status` and `Analyst Response` are optional but recommended because the batch importer can detect analyst progress replies such as:

- `Kindly share statement`
- `Mpesa statement shared. Code 142140`
- `This analysis has been shared`
- `The CRB has been shared`
- `Approved / please proceed`
- `Rejected / declined`

When these replies appear after a request in the export, the importer links them to the pending request and writes the latest stage into `Analysis Status` and the reply trail into `Analyst Response`.

For `/batch`, the bot can also extract attachment filenames from WhatsApp exports, for example:

```text
IMG-20260316-WA0004.jpg (file attached)
```

Actual media files are only available if the WhatsApp export zip includes those files. A text-only export can only provide filenames or `<Media omitted>`, not real file content.

## Admin Configuration

In Django Admin, create or update the group configuration:

- Workflow preset/type: `spin_credit_analysis`
- Sheet ID: SPIN/CRB spreadsheet ID
- Sheet tab: SPIN/CRB worksheet tab
- Header row: row containing the headers above

Optional workflow setting:

```json
{
  "type": "spin_credit_analysis",
  "header_row": 1,
  "media_root_folder": "SPIN CRB Media",
  "legacy_batch_sheet_name": "SPIN Legacy Batch"
}
```

If `media_root_folder` is blank, Drive folders use the Telegram group display name.
