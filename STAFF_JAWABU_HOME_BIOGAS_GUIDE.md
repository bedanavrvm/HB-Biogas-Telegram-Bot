# Staff Guide: Jawabu HomeBiogas Workflow

This workflow imports WhatsApp chat exports from the Jawabu HomeBiogas group.
It is separate from the case/complaint workflow and the order approval workflow.

## Telegram Use

In the configured Jawabu Telegram group, send:

```text
@hb_biogas_cases_bot /batch
```

Attach the WhatsApp `.txt` export or the WhatsApp `.zip` export to that same message. The export should be
from WhatsApp "Export chat" and can include media filenames.


## Recommended Configuration

Use the same bot and the same Google spreadsheet as the Order Approval workflow, but configure Jawabu in a separate Telegram group and worksheet tab:

```text
Telegram group: Jawabu WhatsApp Imports
Workflow preset: Jawabu HomeBiogas
Spreadsheet ID: same workbook used by Order Approval
Worksheet/tab: Jawabu Visits
Header row: 1, unless the sheet uses a different header row
```

This keeps BRO-submitted order data and Jawabu WhatsApp-imported data separate, while still allowing manual comparison in the same workbook.
## What The Bot Extracts

- WhatsApp message date and time
- staff/sender
- customer name
- National ID
- primary phone in `254...` format
- secondary phone, when present
- county
- sub-county/city
- landmark/street
- GPS link
- latitude and longitude
- attached media filenames
- decision text when present in the same WhatsApp message
- raw message for audit

## Required Fields

Every imported record must have:

```text
National ID
Primary Phone
```

The duplicate key is:

```text
National ID + Primary Phone
```

If either value is missing, the record is rejected and shown in the Telegram
reply.

## Duplicate Handling

If the same `National ID + Primary Phone` appears more than once, the bot does
not silently merge the records and does not create a new sheet row for the
duplicate message.

It creates an audit record with:

```text
Duplicate Status: Possible Duplicate
Import Status: Duplicate Needs Review
```

The Telegram reply lists the exact WhatsApp messages to verify manually.

## Expected Sheet Columns

Create these columns in the configured Jawabu worksheet/tab, for example `Jawabu Visits`:

```text
Record ID
Visit Date
WhatsApp Message Time
Staff / Sender
Customer Name
National ID
Primary Phone
Secondary Phone
County
Sub-County / City
Landmark / Street
GPS Link
Latitude
Longitude
Media Filenames
Decision
Decision Note
Duplicate Key
Duplicate Status
Review Notes
Raw Message
```

The default header row is row 1. If your sheet uses another row, set
`workflow.header_row` in Django Admin.
