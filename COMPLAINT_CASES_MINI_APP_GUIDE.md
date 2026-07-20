# Complaint Cases Mini App Guide

## Purpose and data ownership

Complaint Cases is the staff workspace for complaints already ingested into
Django from a configured Telegram group. Approved staff can find a case, record
an update, capture a field location, and upload evidence.

Django owns staff authorization, case-update audit history, location records,
and evidence metadata. The Google complaint register mirrors the current
status, appended resolution notes, resolution date, and Google Maps link. The
original incoming complaint remains intact; Mini App updates never replace it.

This is separate from the original complaint-intake bot commands. Use the Mini
App to work on an existing complaint, not to create a new intake record.

For workbook and Apps Script setup, see
[COMPLAINT_MANAGEMENT_REGISTER_SETUP.md](COMPLAINT_MANAGEMENT_REGISTER_SETUP.md).

## Staff capabilities

- View active (`Open` and `In Progress`) or closed cases in their own group.
- Search by case ID, client name, phone number, customer ID, branch, or words
  in the complaint description.
- Add a status change, append-only note, current GPS location, or evidence.
- Open a saved map pin in Google Maps and view it in the Mini App.
- Open successfully uploaded evidence through its Google Drive link.

The list returns up to 50 matching cases. Refine the search before relying on
it as a full historical report.

### Roles

| Role | Allowed actions | Sensitive-data access |
| --- | --- | --- |
| `OFFICER` (Case officer) | Set `Open` or `In Progress`; add notes, location, and evidence. | Does not receive the original raw Telegram/WhatsApp message. |
| `MANAGER` (Case manager) | All officer actions, plus close and reopen complaints. | Can view the original raw message in case detail. |

Only active, explicitly configured staff can use the Mini App. A valid
Telegram session is authentication, not permission by itself.

## Staff operating procedure

1. Open the pinned **JBL Apps** message in the correct Telegram group.
2. Tap **Complaint Cases**. Do not use a copied link from another group.
3. Use **Active** for open work or **Closed** for completed work. Search
   narrows the selected tab as you type.
4. Open a case and check its identifiers, description, activity, evidence, and
   location before updating it.
5. Choose the current status and add a concise note stating what happened, the
   next step, and the owner.
6. When relevant, tap **Use my current location** and approve location access.
7. Add evidence if it supports the update, then tap **Save update** once and
   wait for the success toast.

Use `In Progress` while follow-up is underway. Only a Case manager may set
`Closed`; the app records the resolution time when it closes a case. A Case
manager can reopen a closed case when necessary.

### Notes and audit history

Each note is appended to the resolution history with the Kenya-local date/time
and configured staff name. It does not replace an older note. Each update also
creates a `CaseUpdate` audit record with status, actor, location, source, and
retry identifier.

Django deduplicates an accidental retry with the same retry identifier. Staff
should still avoid repeatedly tapping **Save update** on a slow network.

## Evidence and location

### Evidence

The default limit is **10 files and 30 MB total per update**. Accepted files:

- JPEG, PNG, or WebP images
- PDF
- Microsoft Word `.doc` or `.docx`

Every upload is hashed. A file already uploaded successfully for the same case
is reused instead of being stored again in Google Drive.

The case update remains saved if its Drive upload fails. The evidence item is
recorded as `failed` and has no link; upload the file again in a new update to
retry it. An administrator can inspect the failure under **Complaint case
evidence** in Django Admin.

Evidence and Drive links can contain customer data. Keep the group Drive folder
restricted to approved staff and do not share links outside the operational
team.

### Location and maps

Location capture uses the device's current geolocation. The app stores latitude
and longitude to six decimal places and saves a Google Maps link. Staff cannot
type coordinates manually in the Mini App.

If location capture fails, enable location access for Telegram/the browser and
try again. A note-only update remains possible. The in-app map is a visual aid;
**Open in Google Maps** is the durable saved link.

## Telegram and BotFather setup

### Canonical web page

Use this URL in BotFather's Mini App configuration:

```text
https://<your-render-domain>/complaints/
```

For example, with a Render domain of
`https://jbl-biogas-telegram-bot.onrender.com`, use:

```text
https://jbl-biogas-telegram-bot.onrender.com/complaints/
```

If BotFather asks for a short name, use a value such as `complaints`, then set
the same value in `COMPLAINT_CASES_MINI_APP_SHORT_NAME`.

The BotFather page URL does not provide group context. Staff must open the app
through the pinned group launcher, which supplies the group ID in Telegram's
`startapp` payload. A bare direct page link can render the shell but cannot
load cases because it has no group context.

### Pinned JBL Apps launcher

In Django Admin, open the group's **Group sheet configuration**:

1. Select **Complaint Cases** in **Pinned JBL Apps Launcher**.
2. Save the configuration.
3. From the configuration list, select the group and run **Publish JBL Apps
   launcher**.

Saving never sends Telegram messages by itself. The bot must be present in the
group and have permission to pin messages. Publishing sends or updates the
group's `JBL Apps` message and pins it.

## Render environment

Configure these values in Render; use real values there, never in Git:

```env
APP_BASE_URL=https://<your-render-domain>
TELEGRAM_BOT_USERNAME=your_bot_username_without_at
COMPLAINT_CASES_MINI_APP_SHORT_NAME=complaints
COMPLAINT_CASES_WEBAPP_REQUIRE_TELEGRAM_AUTH=True
COMPLAINT_CASES_WEBAPP_AUTH_MAX_AGE_SECONDS=86400
COMPLAINT_CASE_MAX_FILES_PER_UPDATE=10
COMPLAINT_CASE_MAX_TOTAL_UPLOAD_MB=30
```

Rules:

- `APP_BASE_URL` has no trailing slash.
- `TELEGRAM_BOT_USERNAME` has no `@`.
- Keep Telegram authentication enabled in production.
- The short name must match BotFather exactly.
- The Google service account and Drive storage settings must be able to update
  the group register and write to the intended Drive area.

## Django Admin configuration

Open:

```text
/admin/core/groupsheetconfiguration/
```

For the complaints group, set:

| Field | Required value |
| --- | --- |
| Enabled | Checked |
| Group ID | Exact Telegram group ID, usually beginning `-100` |
| Display name | Human-readable group name |
| Sheet ID | Complaint register spreadsheet ID |
| Sheet name | Complaint register tab, normally `Complaints Register` |
| Workflow preset | `Case / Complaints` |
| Case header row | `2` for the supplied complaint register layout |
| Pinned JBL Apps Launcher | Include `Complaint Cases` |

The generated workflow type must be `case`. The configured group is the access
boundary: cases, staff, Sheet updates, and evidence must never cross groups.

### Configure staff

On the same group configuration page, use **Complaint case Mini App staff**.
For each staff member set:

- **Active** — uncheck to remove access without destroying audit history.
- **Name** — appears in the Mini App and audit notes.
- **Telegram user ID** — preferred; it remains stable if a username changes.
- **Telegram username** — optional fallback, without `@`.
- **Role** — Case officer or Case manager.
- **Notes** — optional administrator-only context.

At least one Telegram user ID or username is required. Assign manager access
sparingly because managers can close/reopen complaints and view raw messages.

## Sheet synchronization

Before creating the local audit update, the Mini App updates the matching Sheet
row using the case's durable `message_id`. It writes these fields when
applicable:

- `status`
- `resolution_details` (the append-only note history)
- `date_resolved` when the case is closed
- `gps_link` when a location is captured

If the Sheet write fails, the Mini App rejects the update and does not create a
new local `CaseUpdate` record. Evidence uploads happen after a successful case
update, so a Drive failure is recorded separately and does not roll back the
case update.

Keep the required complaint-register headers and row-2 layout from the setup
guide. Staff should work status and resolution fields through the Mini App:
manual Sheet changes do not create a Django audit event and can be overwritten
by the next Mini App update.

## Admin audit and recovery

| Admin area | Use |
| --- | --- |
| Group sheet configurations | Group routing, Sheet mapping, staff list, and launcher selection. |
| Complaint case evidence | Search files by case/actor and inspect failed uploads or Drive URLs. This is read-only audit data. |
| Case updates | Review append-only status, notes, actor, retry, location, and sync history. |

For a failed evidence upload, first confirm the case update appears in activity,
then inspect the evidence audit record. Correct Drive credentials, permissions,
or connectivity and ask staff to upload the file again. Do not delete the audit
record to make a retry work.

## Troubleshooting

| Message or symptom | Likely cause | Action |
| --- | --- | --- |
| “This launcher is missing its Telegram group.” | The page was opened without the group `startapp` payload. | Open Complaint Cases from the pinned JBL Apps message. |
| “Complaint Cases is not configured…” | Missing/disabled group configuration or wrong workflow preset. | Confirm the enabled group ID and `Case / Complaints` preset. |
| “Your Telegram account is not configured…” | No active staff row matches the Telegram identity. | Add/activate the staff row; prefer numeric Telegram ID. |
| Telegram authentication error | Invalid, stale, or missing `initData`. | Close and reopen from Telegram; do not disable production auth to bypass it. |
| “The complaint register could not be updated.” | Sheet access, tab/header mapping, or Google API failure. | Check group Sheet config, service-account sharing, required headers, and logs. The case update was not saved. |
| Location capture fails | Permission denied or unavailable. | Enable location access, then retry; a note-only update is possible. |
| Evidence is `failed` with no Open link | Drive upload failed after the update saved. | Inspect Complaint case evidence in Admin and retry after fixing Drive access. |
| Launcher cannot pin | Bot lacks group pin permission. | Make the bot an admin with pin permission, then publish again. |

## Release checklist

1. Run `python manage.py test core.tests_complaint_cases`.
2. Run `python manage.py check` and `python manage.py makemigrations --check --dry-run`.
3. Run `node --check core/static/miniapp/complaint_cases.js` when JavaScript
   changes.
4. Deploy the Django service. There is no separate Apps Script deployment
   unless the complaint workbook script itself changed.
5. In a non-production test group, verify staff authorization, a note-only
   update, location permission handling, evidence upload, a Drive-failure
   state, and the manager-only close rule.
6. Publish or refresh the JBL Apps launcher only when its selection, BotFather
   short name, bot permissions, or canonical URL changed.

Never test with customer data in an unapproved group, Drive folder, or
spreadsheet. Use synthetic test cases and evidence.
