# TAT Tracker Mini App Guide

## Purpose

The TAT Tracker workflow replaces the old Apps Script web form with a Django-backed Telegram Mini App. The Google workbook remains the reporting/output surface, while Django owns permissions, stage validation, audit history, and command routing.

Use this workflow for the TAT tracker group only. The workflow name in Django is `tat_tracker`, and the visible label is `TAT Tracker`.

## Mini App URLs

The canonical Mini App page is:

```text
https://<your-render-domain>/tat-tracker/
```

For the current Render service, if your base URL is:

```text
https://jbl-biogas-telegram-bot.onrender.com
```

then the Mini App page is:

```text
https://jbl-biogas-telegram-bot.onrender.com/tat-tracker/
```

The app is also reachable through the API-mounted alias:

```text
https://jbl-biogas-telegram-bot.onrender.com/api/tat-tracker/
```

Use `/tat-tracker/` as the BotFather Mini App URL and in documentation. In group chats, the bot sends a normal URL button. When `TAT_TRACKER_MINI_APP_SHORT_NAME` is configured, that button points to the Telegram short link (`https://t.me/<bot>/<short_name>?startapp=...`) so Telegram can open the Mini App without rejecting the button.

Important: do not manually share a URL with `group_id` and `token` for normal use. Staff should open the form from Telegram using `/tat` or `/tracker`, because the bot adds the correct group token and Telegram Mini App authentication data.

## Telegram Short Link

If BotFather short name is configured, Telegram can expose the Mini App as:

```text
https://t.me/<bot_username>/<short_name>
```

Example:

```text
https://t.me/hb_biogas_cases_bot/tattracker
```

This short link is not the same as the web page URL. In group chats, Telegram rejects direct `web_app` buttons with `BUTTON_TYPE_INVALID`, so the bot sends the short link as a normal URL button:

```text
https://t.me/<bot_username>/<short_name>?startapp=<signed-start-payload>
```

The signed start payload is generated automatically by the bot and contains the secure group token.

## BotFather Setup

1. Open Telegram and chat with `@BotFather`.
2. Run `/mybots`.
3. Select the bot used by the TAT tracker group.
4. Open `Bot Settings`.
5. Open `Configure Mini App` or `Menu Button`, depending on the BotFather UI.
6. Set the Mini App URL to:

```text
https://jbl-biogas-telegram-bot.onrender.com/tat-tracker/
```

7. If BotFather asks for a short name, use:

```text
tattracker
```

8. Set Render env `TAT_TRACKER_MINI_APP_SHORT_NAME=tattracker`.

If BotFather does not ask for a short name, keep the web URL configured and leave `TAT_TRACKER_MINI_APP_SHORT_NAME` blank. The bot will still send a secure web link fallback.

## Render Environment Variables

Set these on Render:

```env
APP_BASE_URL=https://jbl-biogas-telegram-bot.onrender.com
TELEGRAM_BOT_USERNAME=your_bot_username_without_at
TAT_TRACKER_MINI_APP_SHORT_NAME=tattracker
TAT_TRACKER_WEBAPP_REQUIRE_TELEGRAM_AUTH=True
TAT_TRACKER_WEBAPP_AUTH_MAX_AGE_SECONDS=86400
```

Notes:

- `APP_BASE_URL` must not end with `/`.
- `TELEGRAM_BOT_USERNAME` should not include `@`.
- `TAT_TRACKER_MINI_APP_SHORT_NAME` must match the short name configured in BotFather.
- If the short name is blank, `/tat` still works, but the button opens as a secure web link instead of a native Telegram Mini App button.

## Django Admin Group Setup

Open Django Admin:

```text
/admin/core/groupsheetconfiguration/
```

Create or update the Telegram group:

- `Group ID`: the Telegram group ID, for example `-1001234567890`
- `Display name`: readable group name, for example `TAT Tracker`
- `Enabled`: checked
- `Sheet ID`: the TAT tracker Google spreadsheet ID
- `Sheet tab`: `TRACKER-SME` or any default tracker tab
- `Workflow preset`: `TAT Tracker`

Save the record.

The generated workflow should look like this:

```json
{
  "type": "tat_tracker",
  "header_row": 2,
  "data_start_row": 5,
  "products": ["logbook", "mjengo", "kilimo", "micro_asset", "sme"],
  "branches": ["Biogas Unit", "Embu", "Nakuru", "West Nairobi"],
  "allow_unconfigured_users": false,
  "default_roles": ["BRO"],
  "staff": []
}
```

## Staff Configuration GUI

Staff access is now configured through Django Admin forms, not by manually editing `workflow.staff` JSON.

Open the saved TAT Tracker group configuration:

```text
/admin/core/groupsheetconfiguration/
```

If the group uses `Workflow preset = TAT Tracker`, the group edit page shows a section named `TAT tracker staff GUI`.

For each staff member, fill:

- `Active`: uncheck to disable access without deleting the row.
- `Name`: display name shown inside the Mini App.
- `Telegram user ID`: preferred. Numeric Telegram user ID is stable even if username changes.
- `Telegram username`: optional fallback, without `@`.
- `Roles`: checkbox list of stages the person can update.
- `Branches`: choose one or more branches, or `All branches`.
- `Products`: choose one or more products, or `All products`.
- `Notes`: optional admin-only note.

Save the group configuration after adding/editing staff. The app automatically converts these GUI rows into the internal `workflow.staff` structure used by Mini App authorization.

There is also a standalone admin list:

```text
/admin/core/tattrackerstaffmember/
```

Use it to search/edit staff across all TAT Tracker groups.

Supported roles:

- `BRO`
- `ADMIN`
- `CA`
- `BM`
- `SECRETARY`
- `CHAIR`
- `LOAN_APPROVER`
- `FINANCE`
- `IT`
- `MANAGEMENT`

Rules:

- `IT` can update any stage.
- Empty `branches` means all branches.
- Empty `products` means all products.
- `branches: ["ALL"]` means all branches.
- `products: ["ALL"]` means all products.
- `active: false` disables that staff member without deleting them.

## Sheet Requirements

The TAT workbook should be one Google spreadsheet with these tabs:

### Product Tracker Tabs

Django writes each case into the matching product tab:

- `TRACKER-SME`
- `TRACKER-LOGBOOK`
- `TRACKER-MJENGO`
- `TRACKER-KILIMO`
- `TRACKER-MICRO-ASSET`

All tracker tabs use the same top-row convention:

- Row `1`: visual title banner, merged across the configured columns.
- Row `2`: actual header row used by staff, filters, and the Mini App sync logic.
- Row `3`: role/help row showing who owns each stage.
- Row `4`: helper notes row.
- Row `5` onward: case data.

The first column must remain `Case ID`. This is the durable record key. Staff can sort/filter the sheet, but they should not edit `Case ID`.

### Support Tabs

The script also creates support tabs:

- `CASE_INDEX`: searchable summary of cases across all product tracker tabs.
- `AUDIT LOG`: append-only log of Mini App stage changes.
- `DASHBOARD`: lightweight formula dashboard based on `CASE_INDEX`.

`CASE_INDEX` and `AUDIT LOG` are support outputs. The main product tracker row is the critical sync target.

### Product Tab Columns

Common early columns:

- `Case ID`
- `Client Name`
- `Branch`
- `BRO Name`
- `Amount`
- `Case Created`

Then each product has its workflow-specific stage columns. The setup script writes the correct headers for each product:

- SME has the shorter SME path without TAT committee decision columns.
- Logbook has `Valuation Ready` plus the full TAT/decision/sanctions path.
- Mjengo, Kilimo, and Micro Asset use the no-valuation TAT/decision/sanctions path.

Common ending columns:

- `Status`
- `Remarks / Delays`
- `TAT Hours`
- `TAT Days`

Do not move or rename columns unless the Django `core/services/tat_tracker.py` product layout is updated at the same time.

### What If A Sheet Row Is Deleted?

The Django database is the system of record for the Mini App. The sheet is the reporting/front-office surface.

If a staff member deletes a row from the Google Sheet only:

- The Django case still exists.
- The Mini App can still find the case by `Case ID`.
- On the next update, Django verifies the stored row number before writing.
- If the old row now contains a different `Case ID`, Django searches column A for the correct `Case ID`.
- If the `Case ID` is no longer found in the sheet, Django appends the case again as a new row.

This prevents accidental overwriting of the wrong row after sorting, row deletion, or manual edits.

Best practice:

- Do not delete active rows from the sheet.
- Use `Status`, `Remarks / Delays`, and the Mini App workflow stages to close or explain a case.
- For a mistaken test record, delete it from Django Admin first, then remove the sheet row if you also want it gone from the reporting sheet.
- If you clear the sheet manually, expect existing Django cases to reappear when they are updated again.

### Resetting Local TAT Test Data

The Django Admin `Reset local DB data` button for a TAT Tracker group clears local `TatTrackerCase` and `TatTrackerEvent` records for that Telegram group. It does not clear Google Sheet rows, filters, validations, or Drive files.

For a clean test reset:

1. Use `Reset local DB data` in the group configuration.
2. Manually clear test rows from the product tracker tabs if you also want the sheet empty.
3. Keep rows 1-4 intact because the setup script and Mini App expect data to start on row 5.

## Sheet Setup Script
Use this file for Google Sheet formatting and validations:

```text
tat_tracker_apps_script.gs
```

Install it in the TAT tracker workbook:

1. Open the Google Sheet.
2. Go to `Extensions -> Apps Script`.
3. Paste `tat_tracker_apps_script.gs`.
4. Save.
5. Run `setupTatTrackerWorkbook()` once.
6. Grant permissions.

The script creates/refreshes:

- Tracker tabs for SME, Logbook, Mjengo, Kilimo, and Micro Asset if they are missing.
- `CASE_INDEX`, `AUDIT LOG`, and `DASHBOARD` support tabs if they are missing.
- Legacy `JBL-*` / `HOCC-*` sheet and range protections from the old tracker script are removed where the current user has permission, because Django must write `CASE_INDEX`, `AUDIT LOG`, and tracker rows.
- Branch, decision, sanctions, register, register approval, and status dropdowns from row 5 downward. Branch values are `Biogas Unit`, `Embu`, `Nakuru`, and `West Nairobi`.
- Amount validation by product from row 5 downward.
- Date/time and amount number formats from row 5 downward.
- TAT Hours and TAT Days formulas from row 5 downward.
- Conditional row highlighting by `Status` and TAT target from row 5 downward.
- Direct conditional highlighting on the `TAT Hours` and `TAT Days` cells: near target is yellow, over target is red.
- Traffic-light highlighting on every workflow stage column from row 5 downward: completed stages are green, pending stages within target are amber, and pending stages over target are red.

Django does not write into `TAT Hours` or `TAT Days`. Those are formula-owned sheet columns. If Google Sheets shows `Invalid: ... violates data validation rule` on those columns, run `TAT Tracker -> Refresh formulas only`; this clears stale validation from the formula columns and reapplies the formulas.


The script does not write, format, merge, unmerge, freeze, unfreeze, filter, or resize rows 1-3. It does not standardize visual headers. Keep the tracker visual design in the workbook/template itself.

### TAT Target Setup

The target is configured in `tat_tracker_apps_script.gs`:

```js
TAT_HOURS_TARGET: 336,
```

`336` means 336 hours, which is 14 days.

To change the target:

1. Open the Google Sheet.
2. Go to `Extensions -> Apps Script`.
3. Edit `TAT_HOURS_TARGET`.
4. Save the script.
5. Reload the Google Sheet.
6. Run `TAT Tracker -> Refresh status/TAT highlighting`.
7. Run `TAT Tracker -> Refresh formulas only` if formula cells need to be rebuilt.

Conditional highlighting from row 5 downward:

- Near target: open case above 80% of target, highlighted light yellow.
- Over target: open case above target, highlighted light red.
- Completed late: `TAT Hours` above target, row highlighted light purple.
- TAT value cells: above 80% of target highlighted yellow; above target highlighted red.
- Every stage cell: green means completed, amber means pending but still within target, red means pending and over target.
- Status highlighting still applies for `Disbursed`, `Rejected`, `Declined`, `Deferred`, `Stalled`, and `Pending Docs`.

Do not copy old tracker trigger/webapp logic into this workbook. Django/Mini App owns case creation, case IDs, staff permissions, stage ordering, timestamp writes, sheet sync, and audit events. The Apps Script is only for sheet setup and validation guardrails.

Menu added by the script:

- `TAT Tracker -> Setup / refresh workbook`
- `TAT Tracker -> Remove legacy protections`
- `TAT Tracker -> Refresh validations only`
- `TAT Tracker -> Refresh formulas only`
- `TAT Tracker -> Refresh status/TAT highlighting`
- `TAT Tracker -> Create support tabs`
- `TAT Tracker -> Show setup notes`

## Commands In Telegram

In the configured TAT tracker group, staff should tag the bot:

```text
@your_bot /tat
```

or:

```text
@your_bot /tracker
```

The bot replies with an `Open TAT Tracker Mini App` URL button when Mini App short name is configured. This avoids Telegram's `BUTTON_TYPE_INVALID` error in groups. If the short name is not configured, it replies with `Open TAT Tracker`, which opens the secure web fallback link.

## What Staff Can Do In The Mini App

The Mini App supports:

- Create a new TAT case.
- Select product: `SME`, `Logbook`, `Mjengo`, `Kilimo`, `Micro Asset`.
- Select branch.
- Enter client name, BRO name, and amount.
- View recent cases.
- View action-required cases for the staff member's role.
- Search by case ID, client name, branch, or BRO name.
- Open a case and update only the stage assigned to the staff member's role.
- View audit history for a case.

## Case ID Format

Case IDs are generated by Django, per group and product, using the current year:

```text
JBL-SME-2026-001
JBL-LB-2026-001
JBL-MJ-2026-001
JBL-KI-2026-001
JBL-MA-2026-001
```

The sequence is independent per product prefix.

## Stage Control

The app enforces stage order. A user cannot update a later stage before the previous required stage is complete.

Examples:

- `ADMIN` cannot verify MPESA until `BRO` marks MPESA as sent.
- `FINANCE` cannot disburse until register approval is complete.
- `BRO` cannot apply on system if sanctions are required but not met.

## Testing After Deployment

1. Confirm Render deployment is live.
2. Confirm migrations ran successfully.
3. Confirm the group exists in Django Admin with `workflow.type = tat_tracker`.
4. Confirm the sheet is shared with the Render Google service account.
5. In Telegram group, send:

```text
@your_bot /tat
```

6. Open the button.
7. Create a test case.
8. Confirm the row appears in the correct tracker tab.
9. Confirm `CASE_INDEX` has the case.
10. Confirm `AUDIT LOG` has the create event.
11. Test with a second role user and verify they only see/update their assigned stage.

## Troubleshooting

### Bot says TAT Tracker is not configured

Check Django Admin group configuration:

- The group ID must match the Telegram group ID exactly.
- The group must be enabled.
- Workflow type must be `tat_tracker`.

### Button opens browser instead of Telegram Mini App

Check:

- BotFather Mini App URL is set.
- `TAT_TRACKER_MINI_APP_SHORT_NAME` is set on Render.
- `TELEGRAM_BOT_USERNAME` is correct.
- Render was redeployed after env changes.

### Staff sees unauthorized error

Add the staff member in the `TAT tracker staff GUI` inline on the group configuration, or in `/admin/core/tattrackerstaffmember/`. Prefer Telegram numeric user ID.

### Sheet sync fails

Check:

- Google Sheet is shared with the Render service account.
- Required tabs exist.
- The service account has editor access.
- The configured `Sheet ID` is the correct spreadsheet ID.

### CASE_INDEX or AUDIT LOG does not update

The main tracker row sync is the critical write. `CASE_INDEX` and `AUDIT LOG` are best-effort support syncs. If either fails, the app logs a warning and continues after the main row is written.

## Current Scope

Implemented now:

- Telegram command routing.
- Mini App launch.
- Staff authorization.
- Case creation.
- Stage updates.
- Role and sequence validation.
- Main tracker sheet sync.
- `CASE_INDEX` sync.
- `AUDIT LOG` sync.
- Django Admin visibility for TAT cases and events.

Not implemented yet:

- Scheduled stalled-case reminders.
- Weekly digest emails.
- STAFF-sheet driven permissions. Current TAT staff permissions are managed in Django Admin GUI rows.
- Full correction-log parity with the old Apps Script.
