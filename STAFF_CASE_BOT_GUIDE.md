# Staff Telegram Guide: Case And Complaint Workflow

This guide is for staff using the Telegram complaint/case group.

Use the bot tag in group messages:

```text
@hb_biogas_cases_bot
```

In Telegram groups, the bot only processes messages that tag the bot or commands sent to the bot.

## What This Workflow Does

Use this workflow for customer complaints, support cases, technical issues, follow-ups, and case status updates.

The bot reads the message, saves the case, writes it to the configured complaint register, and replies in Telegram with the captured fields.

## Report A New Case

Use this format:

```text
@hb_biogas_cases_bot
CUSTOMER COMPLAINT

NAME:
TEL:
ID:
COUNTY:
NATURE OF THE PROBLEM:
```

Example:

```text
@hb_biogas_cases_bot
CUSTOMER COMPLAINT

NAME: Henry Mwenda
TEL: 0720809218
ID: 24289449
COUNTY: Muranga
NATURE OF THE PROBLEM: Requesting for a jiko relocation
```

Mandatory fields for a complete case:

- `NAME`
- `TEL`
- `ID`
- `COUNTY`
- `NATURE OF THE PROBLEM`

If any mandatory field is missing, the bot rejects the case. It is not saved in the database and it is not written to the sheet. The bot reply shows what is missing so staff can resend the complete case.

## County Field

Type the county using this label:

```text
COUNTY: Muranga
```

The bot writes this into the sheet column named `Branch / Region`.

The sheet dropdown should contain the 47 Kenya counties. Use the county name, not a branch nickname.

## Phone Number Format

You can type the phone number naturally:

```text
TEL: 0720809218
TEL: +254720809218
TEL: 254720809218
```

The bot accepts these formats and writes Kenyan mobile numbers as `254XXXXXXXXX` in the database, bot reply, and Google Sheet.

## Multiple Cases In One Message

Start each case with a separate `CUSTOMER COMPLAINT` heading.

```text
@hb_biogas_cases_bot
CUSTOMER COMPLAINT
NAME: Jane Doe
TEL: 0712345678
ID: ACC123
COUNTY: Nairobi
NATURE OF THE PROBLEM: No gas supply

CUSTOMER COMPLAINT
NAME: John Smith
TEL: 0798765432
ID: ACC456
COUNTY: Kisumu
NATURE OF THE PROBLEM: Gas leakage
```

The bot will split the message and create separate cases.

## Bot Reply After A New Case

A successful reply looks like:

```text
OK. Message received and saved successfully
Case ID: MSG_... (use this for /update)
Captured:
Customer Name: ...
Phone Number: ...
Customer ID: ...
County: ...
Complaint Description: ...
```

Use the `Case ID` shown by the bot for `/update` commands. The spreadsheet `Complaint ID` is for sheet display and reporting.

## Update An Existing Case

Best method: reply to the original case message or the bot confirmation message.

Use this format:

```text
@hb_biogas_cases_bot
STATUS: resolved
NOTE: Jiko was relocated and the customer confirmed it is working.
```

Other examples:

```text
@hb_biogas_cases_bot
STATUS: pending
NOTE: Customer was not reachable. Will call again tomorrow.
```

```text
@hb_biogas_cases_bot
STATUS: scheduled
NOTE: Technician visit booked for Friday morning.
```

The note is written to `Resolution Details` as plain text. The timestamp and sender are kept in the audit record, not repeated inside `Resolution Details`.

## Update By Case ID

If you are not replying to the original message, use the Case ID from the bot reply.

```text
@hb_biogas_cases_bot /update MSG_ABC123 Status: resolved - Customer confirmed gas is working.
```

Use `MSG_...`, not the spreadsheet `Complaint ID`.

## Status Words The Bot Understands

Closed/resolved examples:

```text
resolved
fixed
done
managed
closed
repaired
sorted
completed
```

In-progress examples:

```text
scheduled
in progress
ongoing
assigned
contacted
awaiting
```

Open/pending examples:

```text
pending
not reachable
unreachable
no answer
not resolved
phone off
```

## Useful Commands

In a group, tag the bot before the command:

```text
@hb_biogas_cases_bot /help
```

The number after a command is usually the maximum number of results to show.

| Command | Example usage | Purpose |
| --- | --- | --- |
| `/last` | `/last 5` | Show the latest cases from this group. |
| `/recent` | `/recent 10` | Show the latest cases from this group. |
| `/case` | `/case MSG_ABC123` | Show one case in detail using its bot Case ID. |
| `/update` | `/update MSG_ABC123 Status: resolved - Customer confirmed gas is working.` | Update a case status and resolution note. |
| `/search` | `/search gas leakage` | Search names, phone numbers, IDs, complaint text, and raw messages. |
| `/today` | `/today` | Show cases reported today. |
| `/week` | `/week` | Show cases reported this week. |
| `/unsynced` | `/unsynced 10` | Show recent cases not synced to Google Sheets. |
| `/phone` | `/phone 0712345678` | Find cases by phone number. `07...`, `254...`, and `+254...` formats are accepted. |
| `/id` | `/id ACC123` | Find cases by customer or account ID. |
| `/open` | `/open 10` | Show cases not marked closed. |
| `/pending` | `/pending 10` | Show cases with no status set. |
| `/closed` | `/closed 10` | Show closed cases. |
| `/stale` | `/stale 7` | Show cases older than 7 days that are not closed. |
| `/errors` | `/errors 10` | Show cases with Google Sheets sync errors. |
| `/missing` | `/missing phone 10` | Show cases missing `phone`, `id`, or `name`. |
| `/lowconfidence` | `/lowconfidence 10` | Show partial or incomplete historical cases. |
| `/risk` | `/risk high 10` | Show cases by risk level. |
| `/duplicates` | `/duplicates 30` | Show repeated phone numbers or customer IDs in the last 30 days. |
| `/top regions` | `/top regions 7` | Show the most common regions or counties in the last 7 days. |
| `/top issues` | `/top issues 7` | Show the most common complaint categories in the last 7 days. |
| `/summary today` | `/summary today` | Show status and sync totals for today. |
| `/summary week` | `/summary week` | Show status and sync totals for this week. |
| `/batch` | `/batch` with a WhatsApp `.txt` export attached | Import complete complaint cases from a WhatsApp chat export. |
| `/sync` | `/sync` | Refresh Django records from the configured Google Sheet. |
| `/group` | `/group` | Show this Telegram group's workflow and sheet routing. |
| `/health` | `/health` | Show database, group configuration, and recent processing health. |
| `/help` | `/help` | Show the commands available for this group. |

Telegram may show command suggestions when you type `/` or the first letters of a command. The visible command list depends on the workflow configured for that group.

## WhatsApp Export Batch Import

Use `/batch` when you have a WhatsApp chat export containing several complaint reports.

Recommended method:

```text
@hb_biogas_cases_bot /batch
```

Attach the WhatsApp `.txt` export to that same Telegram message.

You can also paste the export text after the command:

```text
@hb_biogas_cases_bot /batch
23/05/2026, 12:46 - Staff Name: CUSTOMER COMPLAIN
NAME: JANE DOE
TEL: 0712345678
ID: A12345
COUNTY: KISUMU
NATURE OF THE PROBLEM: No gas supply
```

The bot reads common WhatsApp export lines such as:

```text
23/05/2026, 12:46 - Staff Name: message
[23/05/2026, 12:46] Staff Name: message
```

Only complaint entries are processed. Normal chat messages and WhatsApp system lines are skipped. Each complaint must still include `NAME`, `TEL`, `ID`, `COUNTY`, and `NATURE OF THE PROBLEM`; incomplete entries are rejected and listed in the batch summary.

Before importing the export, the bot refreshes the local case database from the configured Google Sheet. After importing, it refreshes again so the Django admin/live viewer reflects the sheet. This keeps manual sheet edits, deletions, and bot imports aligned.

If the same export is sent again, existing cases are detected as duplicates using the WhatsApp sender, message text, and WhatsApp timestamp.

## Common Mistakes

Do not send a complaint without tagging the bot.

Do not leave out the customer phone, ID, or county. They are required for a complete case.

Do not update a case by writing only:

```text
Managed
```

Use:

```text
@hb_biogas_cases_bot
STATUS: managed
NOTE: Repaired leaking pipe and customer confirmed gas is working.
```

Do not use the spreadsheet `Complaint ID` for `/update` unless the bot has been changed to support that. Use the bot `Case ID: MSG_...`.

## Troubleshooting

If the bot says a field is missing, resend the case with the missing field filled.

If the bot says the case was rejected, add the missing mandatory fields and resend the full case. Rejected cases are not saved.

If the bot says the case was partially processed, the mandatory intake passed but a later step, such as sheet sync, needs checking. Review the bot reply and the Google Sheet row.

If the bot does not reply, check that the bot was tagged and that the group is configured. Send:

```text
@hb_biogas_cases_bot /group
```

If the sheet is unavailable, the bot may save the case in the database and retry or require admin follow-up.
