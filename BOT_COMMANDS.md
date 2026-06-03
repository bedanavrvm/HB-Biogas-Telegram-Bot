# Telegram Bot Commands

The bot supports read-only commands for checking recently captured cases, data quality, sync state, and group routing. In Telegram groups, commands are only handled when the bot is tagged and the message contains actual command text.

Example:

```text
@hb_biogas_cases_bot /last 5
```

In a direct chat, the command can be sent without the mention.

Telegram autocomplete is handled by Telegram's native bot command menu, not by
chat replies. After syncing the command menu, each configured group gets a
workflow-specific command list. Complaint/case groups show case commands, while
order approval groups show `/order`, `/form`, and shared admin checks only.
Staff can type `/` plus a letter, for example `/g` or `/o`, and Telegram will
show matching options to select. In groups, Telegram may insert commands as
`/group@hb_biogas_cases_bot`; the bot accepts that form.

```text
python manage.py sync_telegram_commands
```

## Case Lookup

| Command | Purpose |
|---------|---------|
| `/last 5` | Show the latest 5 cases from the current group. |
| `/recent 10` | Alias for `/last 10`. |
| `/case MSG_ID` | Show one case in detail. |
| `/update MSG_ID Status: resolved - details` | Update a case status and resolution note. |
| `/search text` | Search message ID, customer name, phone, customer ID, complaint text, and raw message. |
| `/today` | Show cases created today. |
| `/week` | Show cases created since the start of the current week. |
| `/phone 0712345678` | Show cases matching a phone number or partial phone number. `07...`, `254...`, and `+254...` formats are accepted. |
| `/id ACC123` | Show cases matching a customer/account ID or partial ID. |

## Status And Follow-Up

| Command | Purpose |
|---------|---------|
| `/open 10` | Show cases not marked `Closed`. |
| `/pending 10` | Show cases with no status set. |
| `/closed 10` | Show cases marked `Closed`. |
| `/stale 7` | Show cases older than 7 days that are not closed. |
| `/risk high 10` | Show cases with the requested risk level. |

## Sync And Data Quality

| Command | Purpose |
|---------|---------|
| `/unsynced 10` | Show recent cases not synced to Google Sheets. |
| `/errors 10` | Show cases with a recorded Google Sheets sync error. |
| `/missing phone 10` | Show cases missing a phone number. Also supports `id` and `name`. |
| `/lowconfidence 10` | Show partial or incomplete cases that need review. |
| `/duplicates 30` | Show repeated phone numbers or customer IDs seen in the last 30 days. |
| `/sync` | Refresh Django case records from the configured Google Sheet. |

## Summaries

| Command | Purpose |
|---------|---------|
| `/summary today` | Show status and sync totals for today. |
| `/summary week` | Show status and sync totals for the current week. |
| `/top regions 7` | Show the most common regions in the last 7 days. |
| `/top issues 7` | Show the most common complaint categories in the last 7 days. |

## Admin Checks

| Command | Purpose |
|---------|---------|
| `/group` | Show the current chat's sheet routing configuration. |
| `/health` | Show database, group configuration, case count, and unsynced count. |
| `/help` | Show the available commands in Telegram. |

## Limits

- Numeric result limits are capped at 20 rows.
- Day windows are capped at 365 days.
- Search text is capped at 80 characters.
- Commands are scoped to the Telegram group that sent the command.
- Most lookup commands refresh the current group's Django records from Google Sheets before returning results.

## Examples

```text
@hb_biogas_cases_bot /last 5
@hb_biogas_cases_bot /case MSG_ABC123
@hb_biogas_cases_bot /update MSG_ABC123 Status: resolved - Customer confirmed gas is working.
@hb_biogas_cases_bot /phone 0712
@hb_biogas_cases_bot /missing phone 10
@hb_biogas_cases_bot /duplicates 30
@hb_biogas_cases_bot /summary today
@hb_biogas_cases_bot /sync
```
