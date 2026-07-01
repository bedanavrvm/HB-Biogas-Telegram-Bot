# Telegram Staff User Manuals

This file links the staff-facing Telegram guides for the supported workflows.

## Complaint / Case Workflow

Use this guide for groups that receive customer complaints and support cases:

[Staff Telegram Guide: Case And Complaint Workflow](STAFF_CASE_BOT_GUIDE.md)

Main staff actions:

- Report a new case.
- Capture customer county into `Branch / Region`.
- Include all mandatory complaint fields: `NAME`, `TEL` or `ID`, and `NATURE OF THE PROBLEM`. Add both `TEL` and `ID` when available for reporting/filtering. If only one identifier is present, the case is saved with `Status = Review Needed`.
- Update case status.
- Search cases by phone, ID, customer name, or text.
- Check open, pending, closed, stale, duplicate, and incomplete cases.

Complaint messages missing customer name, problem description, or both identifiers are rejected. If only `TEL` or only `ID` is present, the case is saved with `Status = Review Needed` for manual completion.

Core commands:

```text
/help
/last 5
/case MSG_ID
/update MSG_ID Status: resolved - details
/search text
/phone 0712345678
/id ACC123
/summary today
/group
/health
```

## Order Approval Workflow

Use this guide for groups that collect BRO order approval details:

[Staff Telegram Guide: Order Approval Workflow](STAFF_ORDER_APPROVAL_TELEGRAM_GUIDE.md)

Main staff actions:

- Open the Telegram Web App form.
- Create or edit order rows by ID number.
- Use ID suggestions while typing.
- Phone numbers are written as `254XXXXXXXXX`.
- Upload ID photos, LAF documents, and other files.
- Review form and Telegram success/error responses.
- Use `/health` for workflow, upload-limit, and audit diagnostics.

The order approval guide also documents:

- True edit behavior, including clearing blank fields.
- Stale-edit protection.
- Form validation and standardized dropdown values.
- Upload limits, low-memory handling, Drive naming, and duplicate media.
- Structured chat fallback and follow-up media.
- Command examples and troubleshooting.

Core commands:

```text
/order
/form
/help
/group
/health
```

## Group-Specific Commands

Telegram command suggestions depend on the workflow configured for the group.

- Complaint groups show complaint/case commands.
- Order approval groups show order form commands.
- Jawabu HomeBiogas groups show the Jawabu batch import command.
- Case management `/batch` imports process the full WhatsApp export by default; staff should not split normal exports manually.
- Large case management `/batch` imports may reply `WhatsApp batch import started` first, then send the final summary after background processing finishes.

If staff see the wrong commands, ask an admin to check the group's workflow preset in Django Admin and rerun command sync if needed.

## Jawabu HomeBiogas Workflow

Use this guide for groups that import Jawabu WhatsApp visit exports:

[Staff Telegram Guide: Jawabu HomeBiogas Workflow](STAFF_JAWABU_HOME_BIOGAS_GUIDE.md)

Core commands:

```text
/batch
/help
/group
/health
```

## Bot Tag

In Telegram groups, staff should tag the bot:

```text
@hb_biogas_cases_bot /help
```

The bot username can be changed in deployment/configuration, so use the actual bot username shown in Telegram if it differs.
