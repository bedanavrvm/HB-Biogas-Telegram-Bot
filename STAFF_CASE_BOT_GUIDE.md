# Staff Guide: Reporting and Updating Biogas Cases

This guide explains how staff should report new customer complaints and update existing cases in the group chat.

Use this bot tag when reporting or updating cases:

```text
@hb_biogas_cases_bot
```

## 1. Reporting a New Case

Start every new case by tagging the bot. Then write `CUSTOMER COMPLAINT` and fill in the customer details.

Use this format:

```text
@hb_biogas_cases_bot
CUSTOMER COMPLAINT

NAME: customer name
TEL: customer phone number
ID: customer ID or account number
NATURE OF THE PROBLEM: short description of the problem
```

Example:

```text
@hb_biogas_cases_bot
CUSTOMER COMPLAINT

NAME: Henry Mwenda
TEL: 0720809218
ID: 24289449
NATURE OF THE PROBLEM: Requesting for a jiko relocation
```

What matters most:

- Include the customer name.
- Include the phone number or the customer ID/account number. If you have both, include both.
- Clearly describe the problem under `NATURE OF THE PROBLEM`.
- Keep awareness tags at the end if needed, for example `@Supervisor`, but they are not part of the complaint description.

If the customer ID is not available, you can leave it blank as long as the phone number is included:

```text
ID:
```

If the phone number is not available, you can leave it blank as long as the customer ID/account number is included.

## 2. Updating an Existing Case

To update a case, reply to the original case message that was sent to the group.

Do not send the update as a new standalone message. The bot uses your reply to know which case you are updating.

Use this format:

```text
@hb_biogas_cases_bot
STATUS: status
NOTE: what was done or what happened
```

Example for a solved case:

```text
@hb_biogas_cases_bot
STATUS: resolved
NOTE: Jiko was relocated and the customer confirmed it is working.
```

Example for a pending case:

```text
@hb_biogas_cases_bot
STATUS: pending
NOTE: Customer was not reachable. Will call again tomorrow.
```

Example for a scheduled visit:

```text
@hb_biogas_cases_bot
STATUS: scheduled
NOTE: Technician visit booked for Friday morning.
```

## 3. Recommended Status Words

Use simple status words so the bot can understand the update.

Use these when the case is solved:

```text
resolved
fixed
done
managed
closed
repaired
sorted
```

Use these when work is still ongoing:

```text
scheduled
in progress
ongoing
assigned
contacted
awaiting
```

Use these when the case is still open:

```text
pending
not reachable
unreachable
no answer
not resolved
phone off
```

## 4. Common Mistakes to Avoid

Do not forget to tag the bot when reporting a new case.

Do not update a case by sending a fresh message. Always reply to the original case message.

Do not put the status update inside the complaint description.

Do not leave out both the phone number and customer ID. The bot needs at least one of them to identify the customer.

Do not write only:

```text
Managed
```

Instead write:

```text
@hb_biogas_cases_bot
STATUS: managed
NOTE: Repaired leaking pipe and customer confirmed gas is working.
```

## 5. Quick Copy-Paste Templates

New case:

```text
@hb_biogas_cases_bot
CUSTOMER COMPLAINT

NAME:
TEL:
ID:
NATURE OF THE PROBLEM:
```

Case update:

```text
@hb_biogas_cases_bot
STATUS:
NOTE:
```
