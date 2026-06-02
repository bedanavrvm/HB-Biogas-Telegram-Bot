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

If `TEL`, `ID`, or `COUNTY` is missing, the bot may still save the case, but it will mark it as partially processed and reply with the missing field.

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

The order approval workflow normalizes phone numbers to `254XXXXXXXXX`. The case workflow stores the parsed phone as captured by the case parser, so use clear Kenyan numbers where possible.

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

Common commands:

```text
/last 5
/case MSG_ID
/update MSG_ID Status: resolved - details
/search text
/phone 0712345678
/id ACC123
/open 10
/pending 10
/closed 10
/missing phone 10
/lowconfidence 10
/duplicates 30
/summary today
/group
/health
```

Telegram may show command suggestions when you type `/` or the first letters of a command. The visible command list depends on the workflow configured for that group.

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

If the bot says the case was partially processed, check the bot reply and the Google Sheet row.

If the bot does not reply, check that the bot was tagged and that the group is configured. Send:

```text
@hb_biogas_cases_bot /group
```

If the sheet is unavailable, the bot may save the case in the database and retry or require admin follow-up.
