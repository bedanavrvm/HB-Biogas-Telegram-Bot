# Order Approval Render Deployment And Production Testing

This guide enables the separate Telegram group workflow for the live Google Sheet version of `ORDER APPROVAL APRIL 2026.xlsx`.

The complaint/case groups should continue using their existing configuration. Only the new order approval Telegram group should use `workflow.type = "order_approval"`.

## 1. Pre-Deploy Checklist

Before changing Render:

- Ensure the order approval workbook is a live Google Sheet, not only an `.xlsx` file.
- Share the Google Sheet with the same Google service account used by Render.
- Share the target Google Drive media folder with the same service account as Editor.
- Add a `Media URLs` header to row 1 in each tab that the bot will search:
  - `Pending`
  - `178`
  - `179`
  - `180`
  - `181`
- Confirm each searched tab has an `ID NUMBER` header.
- Confirm the BRO writable headers exist where needed:
  - `DATE VISITED`
  - `CUSTOMER NAME`
  - `CONTACTS / PRIMARY`
  - `CONTACTS / SECONDARY`
  - `ID NUMBER`
  - `LOCATION / COUNTY`
  - `LOCATION AND NEAREST LANDMARK`
  - `VISITED BY`
  - `HB STAFF`
  - `DEPOSIT / HB`
  - `DEPOSIT / JBL`
  - `COMMENT`
  - `IS CUSTOMER CREATED ON IMAB?`
  - `CUSTOMER NO`
  - `CREDIT ANALYSIS`
  - `Media URLs`

Do not let the bot create or insert columns in this workbook. Add `Media URLs` manually before enabling the workflow.

## 2. Render Environment Variables To Update

In Render, open the web service:

`Dashboard -> your service -> Environment`

Add or update these new variables:

```text
APP_BASE_URL=https://<your-render-service>.onrender.com
MEDIA_STORAGE_PROVIDER=google_drive
MEDIA_MAX_FILE_SIZE_MB=20
GOOGLE_DRIVE_MEDIA_FOLDER_ID=<drive-folder-id>
ORDER_APPROVAL_WEBAPP_ENABLED=True
ORDER_APPROVAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True
ORDER_APPROVAL_WEBAPP_AUTH_MAX_AGE_SECONDS=86400
```

`GOOGLE_DRIVE_MEDIA_FOLDER_ID` is the folder ID from the Drive folder URL:

```text
https://drive.google.com/drive/folders/<drive-folder-id>
```

Confirm these existing variables are already set correctly:

```text
TELEGRAM_BOT_TOKEN=<bot-token>
TELEGRAM_BOT_USERNAME=hb_biogas_cases_bot
GOOGLE_SERVICE_ACCOUNT_FILE=<path-to-service-account-json-on-render>
DATABASE_URL=<render-postgres-url>
DJANGO_SECRET_KEY=<secret>
DEBUG=False
ALLOWED_HOSTS=<your-render-host>
API_AUTH_TOKEN=<manual-api-token>
```

Usually you do not need to change these existing complaint workflow variables:

```text
GOOGLE_SHEET_ID=<default-complaint-sheet-id>
GOOGLE_SHEET_TAB_NAME=Complaints Register
GROUP_MAPPING_JSON=<optional-existing-config>
```

Preferred setup for the new group is Django admin, not `GROUP_MAPPING_JSON`, because it avoids replacing or breaking existing group JSON.

`APP_BASE_URL` is required for the Telegram Web App button. It must be the public HTTPS Render URL with no trailing slash.

## 3. Deploy The Code

Push this branch to the Git repo connected to Render, then trigger a Render deploy.

The existing `start.sh` runs:

```bash
python manage.py migrate --noinput
python manage.py createsuperuser_env
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

## 4. Prepare Telegram Group

Create a separate Telegram group for order approval updates.

Recommended Telegram setup:

- Add `@hb_biogas_cases_bot` to the group.
- Make the bot an admin, or disable BotFather group privacy for this bot.
- In BotFather, set the bot Web App domain to the Render domain if Telegram blocks the button:

```text
/setdomain
hb_biogas_cases_bot
<your-render-service>.onrender.com
```

- Ask staff to use:

```text
@hb_biogas_cases_bot /order
```

- The bot replies with an `Open Order Approval Form` button.
- The button opens a signed form link for that Telegram group.
- Staff fill the form and submit photos/documents there.
- Staff may still send follow-up photos/documents as replies to the original chat update message if they use the structured chat workflow.

To find the Telegram group ID:

1. Add the bot to the group.
2. Send a test message tagging the bot:

```text
@hb_biogas_cases_bot test group id
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
sheet_name: Pending
```

Use `Pending` for `sheet_name` even though the workflow searches multiple tabs. The order approval service reads the tab list from `workflow.search_sheet_names`.

Leave `sheet_schema` empty unless you are deliberately changing the complaint schema for this group. This workflow does not use the complaint parser schema.

In `Workflow Preset`, select:

```text
Order Approval
```

Leave these defaults unless the workbook tabs change:

```text
order_approval_search_tabs: Pending, 178, 179, 180, 181
order_approval_match_field: ID NUMBER
order_approval_media_field: Media URLs
```

When you save, Django admin generates this `workflow` JSON automatically:

```json
{
  "type": "order_approval",
  "match_field": "id_number",
  "search_sheet_names": ["Pending", "178", "179", "180", "181"],
  "media_field": "media_urls"
}
```

Leave `parser_rules` empty.

Save the configuration. Saving clears the runtime group routing cache.

Future workflow presets are defined in `core/services/workflow_presets.py`. For new group types, add one preset there so admin setup stays the same: group ID, sheet ID, workflow preset, save.

Preset behavior and current group types are documented in `WORKFLOW_PRESETS.md`.

## 6. Optional Environment-Only Group Setup

Use this only if Django admin is not available.

Add the new group to `GROUP_MAPPING_JSON` without removing existing groups:

```json
{
  "-100EXISTING_COMPLAINT_GROUP": {
    "sheet_id": "existing-complaint-sheet-id",
    "sheet_name": "Complaints Register"
  },
  "-1001234567890": {
    "sheet_id": "live-order-approval-sheet-id",
    "sheet_name": "Pending",
    "workflow": {
      "type": "order_approval",
      "match_field": "id_number",
      "search_sheet_names": ["Pending", "178", "179", "180", "181"],
      "media_field": "media_urls"
    }
  }
}
```

Redeploy after changing `GROUP_MAPPING_JSON`.

Do not use this method if admin-managed configurations already exist and are easier to maintain.

## 7. Production Smoke Test

Pick an ID that exists once in exactly one searched tab.

First test the Telegram Web App form:

1. Send this in the order approval group:

```text
@hb_biogas_cases_bot /order
```

2. Tap `Open Order Approval Form`.
3. Fill `ID number` and a few BRO fields.
4. Submit.

Expected:

- The Web App shows a success message.
- The Telegram Web App closes after success.
- The matching Google Sheet row is updated.
- `Core -> Order approval updates` has a `success` record.

Then test the fallback structured chat workflow by sending:

```text
@hb_biogas_cases_bot
ID: 113650221
DATE VISITED: 09/05/2026
CUSTOMER NAME: PATRICK MWANGI MAINA
PRIMARY PHONE: 0740614990
SECONDARY PHONE:
COUNTY: MURANGA
LANDMARK: GITURI NEAR KAGANDA CENTRE
VISITED BY: JOHN & KIBINGE
HB STAFF: THOMAS
HB DEPOSIT: 5000
JBL DEPOSIT: 0
COMMENT: Approved
IMAB CREATED: CREATED
CUSTOMER NO: 15118
CREDIT ANALYSIS: Pending
```

Expected bot reply:

```text
OK. Order approval updated.
ID: 113650221
Customer: PATRICK MWANGI MAINA
Sheet: <tab>, row <number>
Fields updated: <count>
Files stored: 0
```

Then verify:

- The matching row was updated in the correct tab.
- Only the supplied BRO fields changed.
- Complaint group behavior is unchanged.
- `Core -> Order approval updates` has a `success` record.

## 7.1 Web App Authentication Notes

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

## 8. Attachment Test

Send the same structured message with one photo or PDF attached.

Expected:

- The bot uploads the file to Google Drive.
- The Drive link is appended to `Media URLs`.
- `Core -> Media attachments` shows `upload_status = success`.

Then send another photo or PDF as a reply to the original update message.

Expected:

- The bot links the file to the same ID and same sheet row.
- `Media URLs` keeps the old link and appends the new link on a new line.

## 9. Negative Tests

No matching row:

- Send an ID that is not in `Pending`, `178`, `179`, `180`, or `181`.
- Expected reply says no row was found.
- The sheet is not updated.
- Media is stored as traceable unlinked media if an ID was present.

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

## 10. Rollback / Disable

Fastest disable:

1. Go to Django admin.
2. Open the order approval `GroupSheetConfiguration`.
3. Uncheck `enabled`.
4. Save.

Alternative:

- Remove or change `workflow.type` from `order_approval`.
- Redeploy only if using `GROUP_MAPPING_JSON`.

Existing complaint/case groups are separate and should not be affected.
