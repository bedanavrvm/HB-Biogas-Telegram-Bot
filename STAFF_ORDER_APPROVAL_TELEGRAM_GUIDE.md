# Staff Telegram Guide: Order Approval Workflow

This guide is for staff using the Telegram order approval group.

Use the bot tag in group messages:

```text
@hb_biogas_cases_bot
```

The order approval group is separate from the complaint/case group. Its main task is to open the Telegram Web App form, save BRO visit details, update the order approval sheet, and upload supporting media to Google Drive.

## Recommended Method: Use The Form

In the order approval Telegram group, send:

```text
@hb_biogas_cases_bot /order
```

or:

```text
@hb_biogas_cases_bot /form
```

The bot replies with an `Open Order Approval Form` button. Tap it to open the form.

## What The Form Does

The form lets staff:

- Create a new order row when the ID does not exist.
- Load and edit an existing order row when the ID already exists.
- Search possible ID matches while typing the first few digits.
- Enter BRO visit details.
- Upload ID photos, LAF documents, and other files.
- Save media links to the `Media URLs` column.

## Find An Existing Order

In the form:

1. Start typing the customer's ID number.
2. After at least 3 digits, possible matches appear.
3. Tap a match to load the existing row.
4. Edit the fields that need changes.
5. Submit the form.

You can also type the full ID and tap `Load existing`.

If no row is found, submitting the form creates a new row.

## Important Edit Behavior

When an existing row is loaded, blank fields in the form can clear existing sheet values. This is intentional for true editing.

Before submitting an edit:

- Confirm the ID is correct.
- Confirm the loaded customer row is the correct one.
- Fill fields you want to update.
- Leave a field blank only if it should be blank in the sheet.

## Phone Number Format

Use Kenyan `254` format:

```text
254740614990
```

The form also converts common formats when possible:

```text
0740614990
+254740614990
254740614990
```

Invalid examples:

```text
7406149900
12345
```

If the number is invalid, the form shows an error before writing to the sheet.

## Required ID Field

`ID number` is required.

The bot uses the ID number to:

- Search existing rows.
- Create or update the correct order row.
- Put media in the correct Drive folder.
- Keep audit records linked to the customer/order.

## Form Fields

Customer section:

- `ID number`
- `Date visited`
- `Customer name`
- `Branch`
- `Primary phone`
- `Secondary phone`

Visit section:

- `County`
- `Visited by`
- `HB staff`
- `IMAB created`
- `Landmark`

Approval section:

- `HB deposit`
- `JBL deposit`
- `Customer no`
- `Credit analysis`
- `Final decision`
- `Comment`

Files section:

- `ID photos`
- `LAF document`
- `Other files`

## Dropdowns And Standard Values

Use the dropdowns where available.

Current decision options:

```text
Approved
Rejected
Deferred
Under Review
```

Current credit analysis options:

```text
Approved
Pending
Rejected
```

Branch options are controlled by configuration. If a branch is missing, ask an admin to update the branch list.

## Uploading Files

The form has separate upload slots:

- `ID photos`
- `LAF document`
- `Other files`

You can select more than one file in each slot.

The bot stores files in Google Drive under the configured group/order folder. Files for the same ID go into the same ID folder.

Avoid very large uploads from phones. If the phone shows a low-memory warning:

- Upload fewer files at a time.
- Avoid opening many image previews.
- Upload documents first, then photos in smaller batches.

## Media Duplicates

If the same file is uploaded again with the same content, the backend can reuse the existing Drive upload instead of creating another duplicate file.

If the file content is different, it is treated as a new upload.

## Bot Reply After Submit

After a successful form submission, the bot replies in the Telegram group with a structured summary:

```text
OK. Order Approval updated.

Order
ID: 113650221
Customer: PATRICK MWANGI MAINA

Saved
Fields changed: ...
Files stored: ...
```

If there is an error, the bot replies with what staff should fix.

## Structured Chat Format

The form is preferred. If staff must use chat text, use structured labels:

```text
@hb_biogas_cases_bot
ID: 113650221
DATE VISITED: 25-May-2026
CUSTOMER NAME: PATRICK MWANGI MAINA
BRANCH: MURANGA
PRIMARY PHONE: 254740614990
SECONDARY PHONE:
COUNTY: MURANGA
LANDMARK: GITURI NEAR KAGANDA CENTRE
VISITED BY: JOHN
HB STAFF: THOMAS
HB DEPOSIT: 5000
JBL DEPOSIT: 0
COMMENT: Approved
IMAB CREATED: YES
CUSTOMER NO: 15118
CREDIT ANALYSIS: Pending
FINAL DECISION: Under Review
```

The chat format is stricter than the form. Use exact labels and include `ID`.

## Follow-Up Media In Chat

If media was originally submitted through a Telegram message, follow-up attachments should be sent as replies to the original update message so the bot can link them to the same ID.

For normal staff use, the form upload slots are easier and safer.

## Useful Commands

In the order approval group:

```text
@hb_biogas_cases_bot /order
@hb_biogas_cases_bot /form
@hb_biogas_cases_bot /group
@hb_biogas_cases_bot /health
@hb_biogas_cases_bot /help
```

Telegram may show command suggestions when staff type `/` or the first letters of a command. The visible command list depends on the workflow configured for that group.

## Common Mistakes

Do not use the complaint format in the order approval group.

Do not submit without an ID number.

Do not upload all phone photos at once if the phone has low memory.

Do not manually edit the `Media URLs` column unless an admin asks you to.

Do not change sheet headers. The bot depends on the configured headers.

## Troubleshooting

If the form does not open, send:

```text
@hb_biogas_cases_bot /order
```

If the bot does not reply, send:

```text
@hb_biogas_cases_bot /group
```

If the form says no row was found but you expected one, check:

- The ID number is typed correctly.
- The row exists in the configured order sheet.
- The ID is in the `ID NUMBER` column.
- The sheet tab is included in the configured search tabs.

If upload fails, try fewer files and confirm each file is below the configured max file size.

If the bot reports a duplicate ID, staff should resolve the duplicate rows in the sheet before submitting the update.
