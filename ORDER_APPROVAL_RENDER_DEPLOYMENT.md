# Order Approval Render Deployment And Production Testing

This guide enables the separate Telegram group workflow for the live Google Sheet version of `ORDER APPROVAL APRIL 2026.xlsx`.

The complaint/case groups should continue using their existing configuration. Only the new order approval Telegram group should use `workflow.type = "order_approval"`.

## 1. Pre-Deploy Checklist

Before changing Render:

- Ensure the order approval workbook is a live Google Sheet, not only an `.xlsx` file.
- Share the Google Sheet with the same Google service account used by Render.
- Create the target media folder inside a Google Shared Drive, then add the same service account to that Shared Drive or folder with upload permission.
- Keep row 1 as the visual title banner.
- Put the bot-compatible headers in row 2 of the `Orders` tab.
- Add a `Media URLs` header to row 2 in the `Orders` tab.
- Confirm the `Orders` tab has an `ID NUMBER` header in row 2.
- Confirm the BRO writable headers exist where needed:
  - `ORDER RECORD ID` (recommended, bot-managed stable row identifier)
  - `DATE VISITED`
  - `CUSTOMER NAME`
  - `BRANCH`
  - `ID NUMBER`
  - `CONTACTS / PRIMARY`
  - `CONTACTS / SECONDARY`
  - `COUNTY`
  - `SUB-COUNTY`
  - `LOCATION AND NEAREST LANDMARK`
  - `VISITED BY`
  - `HB STAFF`
  - `DEPOSIT / HB`
  - `DEPOSIT / JBL`
  - `COMMENT`
  - `IS CUSTOMER CREATED ON IMAB?`
  - `CUSTOMER NO`
  - `CREDIT ANALYSIS`
  - `FINAL DECISION`
  - `Media URLs`

Do not let the bot create or insert columns in this workbook. Add row-2 headers manually before enabling the workflow if you are not using the generated template.

`ORDER RECORD ID` is optional for older sheets but recommended. When the column exists, the bot fills it with a short sequential ID such as `JBL-1`, `JBL-2`, and so on. This remains attached to the order even if staff sort/filter the sheet, so staff should not use row numbers as permanent references.

To redesign the existing April workbook into one manageable `Orders` sheet, run:

```bash
python scripts/redesign_order_approval_workbook.py -i "ORDER APPROVAL APRIL 2026.xlsx" -o "ORDER APPROVAL REDESIGNED.xlsx"
```

The redesign script keeps `SOURCE TAB` and `SOURCE ROW` only as migration/audit
metadata. They show where a row came from in the old multi-tab workbook. The
bot does not need them, and fresh templates do not include them.

To create a fresh blank workbook template in the expected one-sheet format, run:

```bash
python scripts/create_order_approval_workbook.py -o order_approval_template.xlsx
```

The generated template includes an `Orders` tab and a visible
`Dropdown Options` tab. Staff can manually add dropdown choices for `BRANCH`,
`COUNTY`, `SUB-COUNTY`, `VISITED BY`, and `HB STAFF` in that options tab. The template also
includes data type validation and final-decision row highlighting.

For a template that includes one example row in `Orders`, run:

```bash
python scripts/create_order_approval_workbook.py --sample-row -o order_approval_template.xlsx
```

Upload the generated `.xlsx` to Google Drive, open it with Google Sheets, then use that live Google Sheet ID in the group configuration.

Media file naming and Drive folder rules are documented in `ORDER_APPROVAL_MEDIA_NAMING.md`.

## 2. Render Environment Variables To Update

In Render, open the web service:

`Dashboard -> your service -> Environment`

Add or update these new variables:

```text
APP_BASE_URL=https://<your-render-service>.onrender.com
MEDIA_STORAGE_PROVIDER=google_drive
MEDIA_MAX_FILE_SIZE_MB=20
ORDER_APPROVAL_MAX_FILES_PER_SLOT=10
ORDER_APPROVAL_MAX_TOTAL_UPLOAD_MB=30
FILE_UPLOAD_MAX_MEMORY_SIZE=0
ORDER_APPROVAL_IMAGE_PREVIEWS_ENABLED=False
ORDER_APPROVAL_IMAGE_PREVIEW_LIMIT=3
GOOGLE_DRIVE_MEDIA_FOLDER_ID=<shared-drive-folder-id>
ORDER_APPROVAL_WEBAPP_ENABLED=True
ORDER_APPROVAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True
ORDER_APPROVAL_WEBAPP_AUTH_MAX_AGE_SECONDS=86400
ORDER_APPROVAL_BRANCH_CHOICES=MURANGA,EMBU
```

`GOOGLE_DRIVE_MEDIA_FOLDER_ID` is the folder ID from the Shared Drive folder URL:

```text
https://drive.google.com/drive/folders/<drive-folder-id>
```

`ORDER_APPROVAL_BRANCH_CHOICES` controls the standardized Web App branch
dropdown. Keep the same uppercase names in the sheet's `Dropdown Options` tab.

Upload limits:

- `MEDIA_MAX_FILE_SIZE_MB` is the maximum size for one selected file.
- `ORDER_APPROVAL_MAX_FILES_PER_SLOT` is the maximum file count per upload slot
  (`ID photos`, `LAF document`, `Other files`).
- `ORDER_APPROVAL_MAX_TOTAL_UPLOAD_MB` is the maximum total selected upload size
  for one form submission.
- `FILE_UPLOAD_MAX_MEMORY_SIZE=0` makes Django spool Web App uploads to
  temporary files instead of retaining them in worker memory.
- `ORDER_APPROVAL_IMAGE_PREVIEWS_ENABLED=False` keeps image thumbnails off by
  default. Staff still see filenames and sizes, and can tap `Show thumbnails`
  when needed.
- `ORDER_APPROVAL_IMAGE_PREVIEW_LIMIT` caps how many thumbnails can be decoded
  in the browser when thumbnails are enabled.

On touch/mobile devices, the Web App automatically uses phone-safe upload mode:

- Image thumbnails are never decoded.
- Each upload slot accepts up to two files per submission.
- Staff can submit additional files later against the same customer ID.
- Telegram shows a `Use phone browser` fallback that opens the same signed form
  outside Telegram's lower-memory embedded browser.

Desktop browsers retain the configured multi-file limit and optional previews.
A practical production starting point is 20 MB per file and 30 MB total per
submission.

Use a Google Shared Drive for media storage. Google service accounts do not have normal My Drive storage quota, so uploads to a regular My Drive folder can fail with `storageQuotaExceeded` even when the folder is shared correctly.

Confirm these existing variables are already set correctly:

```text
TELEGRAM_BOT_TOKEN=<bot-token>
TELEGRAM_BOT_USERNAME=<bot-username-without-at>
TELEGRAM_BOT_DISPLAY_NAME=<bot-display-name>
APP_DISPLAY_NAME=<app-display-name>
GOOGLE_SERVICE_ACCOUNT_FILE=<path-to-service-account-json-on-render>
DATABASE_URL=<render-postgres-url>
DJANGO_SECRET_KEY=<secret>
DEBUG=False
ALLOWED_HOSTS=<your-render-host>
API_AUTH_TOKEN=<manual-api-token>
```

Do not configure group-specific routing in Render env for new groups. Sheet IDs, tab names, group IDs, and workflow presets should be managed in Django admin under `Core -> Group sheet configurations`.

`APP_BASE_URL` is required for the Telegram Web App button. It must be the public HTTPS Render URL with no trailing slash.

## 3. Deploy The Code

Push this branch to the Git repo connected to Render, then trigger a Render deploy.

The existing `start.sh` runs:

```bash
python manage.py migrate --noinput
python manage.py createsuperuser_env
python manage.py sync_telegram_commands
gunicorn config.wsgi:application --log-file -
```

The new migration creates:

- `OrderApprovalUpdate`
- `MediaAttachment`

After deploy, check Render logs for:

```text
Running database migrations...
Starting Django application...
```

Also confirm there are no errors mentioning `0009_orderapprovalupdate_mediaattachment`.

The `sync_telegram_commands` step publishes Telegram's native command
autocomplete menu per configured group. Complaint/case groups get case commands;
order approval groups get `/order`, `/form`, `/group`, `/health`, and `/help`.
It also clears the generic all-group fallback so staff do not see commands from
the wrong workflow. The step is non-fatal in `start.sh`; if Render logs show a
warning, open a Render shell after the service is live and run:

```bash
python manage.py sync_telegram_commands
```

After this sync, Telegram clients can show matching command options as staff
type `/g`, `/o`, and similar command prefixes.

## 4. Prepare Telegram Group

Create a separate Telegram group for order approval updates.

Recommended Telegram setup:

- Add `@<bot_username>` to the group.
- Make the bot an admin, or disable BotFather group privacy for this bot.
- In BotFather, set the bot Web App domain to the Render domain if Telegram blocks the button:

```text
/setdomain
<bot_username>
<your-render-service>.onrender.com
```

- Ask staff to use:

```text
@<bot_username> /order
```

- The bot replies with an `Open Order Approval Form` button.
- The button opens a signed form link for that Telegram group.
- Staff fill the form and submit photos/documents there.
- Staff may still send follow-up photos/documents as replies to the original chat update message if they use the structured chat workflow.

To find the Telegram group ID:

1. Add the bot to the group.
2. Send a test message tagging the bot:

```text
@<bot_username> test group id
```

3. Check Render logs for the incoming `chat.id` or an `Unknown group_id` warning.
4. Use the full negative ID, for example:

```text
-1001234567890
```

If logs do not show the message, check that the bot is admin or privacy is disabled.

## 5. Set The New Group In Django Admin

Open:

```text
https://<your-render-service>.onrender.com/admin/
```

Go to:

```text
Core -> Group sheet configurations -> Add group sheet configuration
```

Set:

```text
enabled: checked
group_id: -1001234567890
display_name: Order Approval
sheet_id: <live-order-approval-google-sheet-id>
sheet_name: Orders
```

Use `Orders` for `sheet_name`. The one-sheet design is easier to audit, filter, and configure than the old batch-tab layout.

Leave `sheet_schema` empty unless you are deliberately changing the complaint schema for this group. This workflow does not use the complaint parser schema.

In `Workflow Preset`, select:

```text
Order Approval
```

Leave these defaults unless the workbook tabs change:

```text
order_approval_search_tabs: Orders
order_approval_match_field: ID NUMBER
order_approval_media_field: Media URLs
order_approval_header_row: 2
order_approval_media_root_folder: <optional Drive folder name; blank uses group display name>
```

`display_name` is also used as the default Drive group folder under
`GOOGLE_DRIVE_MEDIA_FOLDER_ID`. If the Telegram group name changes later,
update `display_name` in admin. If you want Drive to keep a stable folder name
even when the Telegram group is renamed, set `order_approval_media_root_folder`.

When you save, Django admin generates this `workflow` JSON automatically:

```json
{
  "type": "order_approval",
  "match_field": "id_number",
  "search_sheet_names": ["Orders"],
  "create_sheet_name": "Orders",
  "media_field": "media_urls",
  "header_row": 2,
  "media_root_folder": ""
}
```

Leave `parser_rules` empty.

Save the configuration. Saving clears the runtime group routing cache.

Future workflow presets are defined in `core/services/workflow_presets.py`. For new group types, add one preset there so admin setup stays the same: group ID, sheet ID, workflow preset, save.

Preset behavior and current group types are documented in `WORKFLOW_PRESETS.md`.

## 6. Production Smoke Test

Pick an ID that exists once in exactly one searched tab.

First test the Telegram Web App form:

1. Send this in the order approval group:

```text
@<bot_username> /order
```

2. Tap `Open Order Approval Form`.
3. Enter `ID number`.
4. Tap `Load existing`.
5. If a row exists, confirm the form pre-fills the current sheet values.
6. Edit one field and submit.

Expected:

- The Web App shows a success message.
- The Telegram Web App closes after success.
- The matching Google Sheet row is updated, or a new row is created in `Orders` if the ID is new.
- In loaded edit mode, blanked fields clear the corresponding sheet cells.
- `Core -> Order approval updates` has a `success` record.

Then test the fallback structured chat workflow by sending:

```text
@<bot_username>
ID: 113650221
DATE VISITED: 09-May-2026
CUSTOMER NAME: PATRICK MWANGI MAINA
BRANCH: MURANGA
PRIMARY PHONE: 0740614990
SECONDARY PHONE:
COUNTY: MURANGA
SUB-COUNTY: KIHARU
LANDMARK: GITURI NEAR KAGANDA CENTRE
VISITED BY: JOHN & KIBINGE
HB STAFF: THOMAS
HB DEPOSIT: 5000
JBL DEPOSIT: 0
COMMENT: Approved
IMAB CREATED: Yes
CUSTOMER NO: 15118
CREDIT ANALYSIS: Pending
FINAL DECISION: Under Review
```

Expected bot reply:

```text
ENTRY UPDATED

Order record ID: JBL-7
Customer ID: 113650221
Customer: PATRICK MWANGI MAINA
Files stored: 0

Updated fields
- CONTACTS / PRIMARY: updated
- Media URLs: appended
```

The staff response does not expose worksheet names, row numbers, column letters,
or unchanged fields.

Then verify:

- The matching row was updated in the correct tab.
- Only the supplied BRO fields changed.
- Complaint group behavior is unchanged.
- `Core -> Order approval updates` has a `success` record.

## 6.1 Web App Authentication Notes

The form submit endpoint accepts either:

- Telegram Web App `initData` validated with `TELEGRAM_BOT_TOKEN`, or
- The signed group form token generated by `/order`.

Keep this enabled in production:

```text
ORDER_APPROVAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True
```

Do not share copied form links outside the staff group. Links expire based on:

```text
ORDER_APPROVAL_WEBAPP_AUTH_MAX_AGE_SECONDS=86400
```

For a temporary server-side smoke test outside Telegram, you can set:

```text
ORDER_APPROVAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=False
```

Only use that briefly, then turn it back to `True`.

## 7. Attachment Test

Send the same structured message with one photo or PDF attached.

Expected:

- The bot uploads the file to Google Drive.
- The Drive link is appended to `Media URLs`.
- `Core -> Media attachments` shows `upload_status = success`.

Then send another photo or PDF as a reply to the original update message.

Expected:

- The bot links the file to the same ID and same sheet row.
- `Media URLs` keeps the old link and appends the new link on a new line.

## 8. Negative Tests

New ID / no matching row:

- Send an ID that is not in `Orders`.
- Expected result creates a new row in `Orders`.
- Media links are written into `Media URLs` on the new row.

Duplicate ID:

- If the same ID exists in more than one searched tab or row, send an update.
- Expected reply lists matching tabs/rows.
- The sheet is not updated.

Oversize file:

- Send a file larger than `MEDIA_MAX_FILE_SIZE_MB`.
- Expected reply includes a warning.
- `MediaAttachment.upload_status` is `skipped`.

Missing `Media URLs`:

- If a searched tab lacks `Media URLs`, update should fail safely.
- Add the header manually and retest.

## 9. Rollback / Disable

Fastest disable:

1. Go to Django admin.
2. Open the order approval `GroupSheetConfiguration`.
3. Uncheck `enabled`.
4. Save.

Alternative:

- Remove or change `workflow.type` from `order_approval`.

Existing complaint/case groups are separate and should not be affected.
