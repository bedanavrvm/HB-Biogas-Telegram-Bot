# Telegram Staff User Manuals

This file links the staff-facing Telegram guides for the supported workflows.

## Complaint / Case Workflow

Use this guide for groups that receive customer complaints and support cases:

[Staff Telegram Guide: Case And Complaint Workflow](STAFF_CASE_BOT_GUIDE.md)

Main staff actions:

- Report a new case.
- Capture customer county into `Branch / Region`.
- Include all mandatory complaint fields: `NAME`, `TEL`, `ID`, `COUNTY`, and `NATURE OF THE PROBLEM`.
- Update case status.
- Search cases by phone, ID, customer name, or text.
- Check open, pending, closed, stale, duplicate, and incomplete cases.

Incomplete complaint messages are rejected and are not saved to the database or sheet. The bot reply lists the missing fields so staff can resend the complete case.

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

If staff see the wrong commands, ask an admin to check the group's workflow preset in Django Admin and rerun command sync if needed.

## Bot Tag

In Telegram groups, staff should tag the bot:

```text
@hb_biogas_cases_bot /help
```

The bot username can be changed in deployment/configuration, so use the actual bot username shown in Telegram if it differs.
