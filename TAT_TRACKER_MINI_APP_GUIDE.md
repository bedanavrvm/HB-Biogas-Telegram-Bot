# TAT Tracker Mini App Guide

## Purpose

The TAT Tracker workflow replaces the old Apps Script web form with a Django-backed Telegram Mini App. The Google workbook remains the reporting/output surface, while Django owns permissions, stage validation, audit history, and command routing.

## Render environment variables

Set these on Render:

```env
APP_BASE_URL=https://your-render-service.onrender.com
TELEGRAM_BOT_USERNAME=your_bot_username_without_at
TAT_TRACKER_MINI_APP_SHORT_NAME=tattracker
TAT_TRACKER_WEBAPP_REQUIRE_TELEGRAM_AUTH=True
TAT_TRACKER_WEBAPP_AUTH_MAX_AGE_SECONDS=86400
```

`TAT_TRACKER_MINI_APP_SHORT_NAME` is optional. If blank, `/tat` sends a secure web link instead of a Telegram Mini App button.

## Django Admin group setup

Open `Core -> Group sheet configurations` and create/update the Telegram group:

- `Group ID`: Telegram group ID
- `Display name`: human-friendly group name
- `Sheet ID`: the TAT tracker Google spreadsheet ID
- `Sheet tab`: `TRACKER-SME` or any default tracker tab
- `Workflow preset`: `TAT Tracker`
- Save

The generated workflow type is:

```json
{
  "type": "tat_tracker",
  "header_row": 2,
  "data_start_row": 5,
  "products": ["logbook", "mjengo", "kilimo", "micro_asset", "sme"],
  "branches": ["Corporate", "Thika Road", "East Nairobi", "West Nairobi", "Nakuru", "Embu", "Limuru"],
  "allow_unconfigured_users": false,
  "default_roles": ["BRO"],
  "staff": []
}
```

## Staff configuration

Add Telegram users under `workflow.staff`:

```json
{
  "telegram_user_id": "123456789",
  "telegram_username": "staffusername",
  "name": "Jane Officer",
  "roles": ["BRO"],
  "branches": ["Nakuru"],
  "products": ["logbook", "sme"],
  "active": true
}
```

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

`IT` can update any stage. Empty `branches` or `products` means all allowed.

## Telegram use

In the configured group:

```text
@your_bot /tat
```

or:

```text
@your_bot /tracker
```

The bot replies with an Open TAT Tracker button.

## Sheet tabs used

The workflow writes to these existing workbook tabs:

- `TRACKER-SME`
- `TRACKER-LOGBOOK`
- `TRACKER-MJENGO`
- `TRACKER-KILIMO`
- `TRACKER-MICRO-ASSET`
- `CASE_INDEX`
- `AUDIT LOG`

Headers are expected on row 2 and data starts on row 5.
