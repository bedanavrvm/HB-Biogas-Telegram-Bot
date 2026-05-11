# Case Status Updates via Chat - Brainstorm

Created: 2026-05-11  
Context: staff submit complaint cases in Telegram; the bot parses them, stores them in Django, and syncs to Google Sheets. Later, staff need to reply in chat with the status/resolution so the existing row is updated.

## Short Answer

The most natural workflow is:

1. Staff submit a case message with the customer bio/details.
2. Bot saves the case and replies with confirmation.
3. Later, staff reply directly to the original staff case message, not the bot's confirmation.
4. The reply starts with `Status: ...`.
5. The bot uses Telegram `reply_to_message.message_id` to find the original case.
6. The bot updates the existing Google Sheets row and backend record.

This is better than asking staff to copy a case ID, because the original message already contains the customer name, ID, phone, and complaint details. Staff only need to add the outcome.

## Recommended Staff Response Format

Use a simple convention:

```text
Status: resolved
Replaced broken pipe. Customer confirmed gas is working.
```

or:

```text
Status: not reachable
Called 3 times. Phone off.
```

or:

```text
Status: scheduled
Visit planned for Thursday morning.
```

The important part is `Status:` at the start. Everything after it becomes the update note or resolution details.

## Why Require `Status:`?

Without a clear marker, normal chat replies can be mistaken for case updates.

Examples that should not update the sheet:

```text
Okay
Who is handling this?
Call him again
Where is this customer?
```

Examples that should update the sheet:

```text
Status: resolved - jiko relocated successfully
Status: not reachable, customer did not pick
Status: scheduled for Monday
Status: pending, technician not yet assigned
Status: escalated, customer has waited 12 days
```

So the first implementation should be strict:

- Reply must be to a case message.
- Reply text must contain `Status:`.
- If either condition fails, ignore it or return a gentle help message.

## Suggested Status Vocabulary

Keep the sheet values simple and consistent.

| Staff text | Sheet Status | Meaning |
|---|---|---|
| `Status: resolved` | `Closed` | Case solved |
| `Status: closed` | `Closed` | Case solved |
| `Status: managed` | `Closed` | Local staff wording for solved |
| `Status: fixed` | `Closed` | Technical issue fixed |
| `Status: repaired` | `Closed` | Repair completed |
| `Status: scheduled` | `In Progress` | Visit planned |
| `Status: in progress` | `In Progress` | Work started |
| `Status: pending` | `Open` | Not solved yet |
| `Status: not reachable` | `Open` or `In Progress` | Contact attempted, not solved |
| `Status: escalated` | `Open` | Needs attention |

Recommended canonical statuses:

- `Open`
- `In Progress`
- `Closed`

Avoid too many status values in the sheet. Put nuance in `Resolution Details`.

## How the Bot Reply Should Look

### Case Closed

```text
OK. Case updated.
Case: MSG_9A3F12
Customer: Henry Mwenda | 0720809218
Status: Closed
Resolution: Jiko relocated successfully. Customer confirmed.
Date resolved: 11/05/2026
```

### Case Still Open

```text
OK. Case updated.
Case: MSG_9A3F12
Customer: Henry Mwenda | 0720809218
Status: Open
Note: Customer not reachable after 3 calls.
```

### Case Scheduled / In Progress

```text
OK. Case updated.
Case: MSG_9A3F12
Customer: Henry Mwenda | 0720809218
Status: In Progress
Note: Visit scheduled for Thursday morning.
```

### Ambiguous Reply

```text
I found more than one case linked to that message.
Please reply with one of these:
/update MSG_123ABC Status: resolved - details...
/update MSG_456DEF Status: pending - details...
```

## Link Strategy

### Primary: Reply to Original Staff Case Message

Telegram includes this in the webhook payload:

```json
{
  "message_id": 9002,
  "text": "Status: resolved - jiko relocated",
  "reply_to_message": {
    "message_id": 8120,
    "text": "@hb_biogas_cases_bot Henry Mwenda..."
  }
}
```

The bot should use `reply_to_message.message_id = 8120` to find the case created from the original staff message.

Current code already stores the inbound Telegram message ID in `RawMessage.telegram_message_id`. For single-case messages, that is enough:

```text
RawMessage.telegram_message_id = "8120"
ParsedMessage -> ProcessedMessage -> RawMessage
```

### Needed Improvement: Store Root Telegram Message ID

Batch messages are currently split into IDs like:

```text
8120_0
8120_1
8120_2
```

If staff reply to original Telegram message `8120`, exact matching will not find `8120_0`. Also, multiple cases may share the same root message.

Recommended model addition:

```python
source_telegram_message_id = models.CharField(
    max_length=255,
    blank=True,
    default='',
    db_index=True,
    help_text='Original Telegram message_id before batch splitting.'
)

batch_index = models.PositiveIntegerField(null=True, blank=True)
```

Alternative: derive root ID by stripping the suffix from `telegram_message_id`, but explicit fields are safer.

### Secondary: Explicit `/update` Fallback

Staff can still update by case ID when reply-linking is ambiguous:

```text
@hb_biogas_cases_bot /update MSG_9A3F12 Status: resolved - repaired inlet pipe
```

This handles:

- old cases before reply-linking existed
- batch messages with multiple cases
- forwarded screenshots/messages
- cases discussed outside the original thread

## Columns to Update

Only update human workflow columns. Do not touch bot intake columns or formula columns.

| Sheet Column | Field | Updated by chat status? |
|---|---|---|
| `[14] Loan Status` | `loan_status` | Optional later |
| `[15] Loan at Risk` | `loan_at_risk` | Optional when `loan risk: yes/no` |
| `[16] Risk Level` | `risk_level` | Optional when `risk: high/medium/low` |
| `[17] Status` | `complaint_status` | Yes |
| `[18] Resolution Details` | `resolution_details` | Yes |
| `[19] Date Resolved` | `date_resolved` | Yes, only when `Closed` |
| `[20] Days Open` | formula | Never |

For the first version, update only:

- `Status`
- `Resolution Details`
- `Date Resolved`

Add risk and loan fields after the basic workflow is stable.

## Source of Truth Design

Since Google Sheets is the operational source of truth, chat updates should be applied carefully.

Recommended sequence:

1. Parse the chat update.
2. Find the matching `ParsedMessage`.
3. Find the matching sheet row by `message_id`.
4. Write the update to Sheets first.
5. If Sheets update succeeds, update Django fields or run a sheet-to-backend sync for that group.
6. Record an audit trail either way.

This keeps the backend aligned with what staff see in the register.

If Sheets is temporarily unavailable:

- save the update as pending in the backend
- tell staff: `Update received but could not sync to the register. It will be retried.`
- retry later

Do not silently mark the case updated in chat while the sheet failed.

## New Model: CaseUpdate

Add an audit model. This is important because status can change multiple times.

```python
class CaseUpdate(models.Model):
    parsed_message = models.ForeignKey(
        ParsedMessage,
        on_delete=models.CASCADE,
        related_name='case_updates',
    )
    group_id = models.CharField(max_length=100, db_index=True)
    updated_by = models.CharField(max_length=255, blank=True, default='')
    telegram_message_id = models.CharField(max_length=255, blank=True, default='')
    reply_to_telegram_message_id = models.CharField(max_length=255, blank=True, default='')

    old_status = models.CharField(max_length=255, blank=True, default='')
    new_status = models.CharField(max_length=255, blank=True, default='')
    resolution_text = models.TextField(blank=True, default='')
    risk_level = models.CharField(max_length=100, blank=True, default='')
    loan_at_risk = models.CharField(max_length=100, blank=True, default='')

    sync_status = models.CharField(max_length=20, default='pending')
    sync_error = models.TextField(blank=True, default='')
    raw_update_text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
```

This lets us answer:

- who updated the case
- when they updated it
- what they wrote
- what the status was before and after
- whether the sheet update succeeded

## New Service: `case_update_parser.py`

Purpose:

```python
def parse_case_update(text: str) -> dict:
    """
    Parse staff status replies.

    Returns:
    {
        "is_update": True,
        "status": "Closed" | "In Progress" | "Open" | "",
        "resolution_text": "...",
        "date_resolved": date | None,
        "risk_level": "",
        "loan_at_risk": "",
        "confidence": 1.0,
    }
    """
```

Strict first pass:

- require `Status:`
- normalize known words to canonical status
- everything after status phrase becomes resolution/note

Examples:

```text
Status: resolved - pipe replaced
=> Status: Closed
=> Resolution Details: pipe replaced
=> Date Resolved: today

Status: not reachable, phone off
=> Status: Open
=> Resolution Details: not reachable, phone off
=> Date Resolved: blank

Status: scheduled for Monday
=> Status: In Progress
=> Resolution Details: scheduled for Monday
=> Date Resolved: blank
```

Keyword map:

```python
CLOSED_WORDS = {
    'resolved', 'closed', 'managed', 'done', 'fixed',
    'repaired', 'sorted', 'completed', 'complete',
}

IN_PROGRESS_WORDS = {
    'scheduled', 'in progress', 'ongoing', 'assigned',
    'visited', 'contacted', 'awaiting',
}

OPEN_WORDS = {
    'open', 'pending', 'not reachable', 'unreachable',
    'no answer', 'not solved', 'not resolved',
}
```

## New Sheet Method: `update_case_row`

Add to `GoogleSheetsService`:

```python
def update_case_row(self, message_id: str, updates: dict) -> bool:
    """
    Find the row with this message_id and update only allowed human columns:
    Status, Resolution Details, Date Resolved, Risk Level, Loan at Risk.
    """
```

Rules:

- Locate row by the live `message_id` header, not fixed column B.
- Update by header names, not hardcoded indexes.
- Never write formula columns.
- Never rewrite bot intake columns.
- Use `USER_ENTERED` for date columns.
- Preserve existing resolution details by appending, not replacing, unless explicitly requested.

Resolution append format:

```text
[11/05/2026 14:23 - Peter Mwangi] Status: resolved - pipe replaced
```

Appending is safer than overwriting because multiple staff may update the same case.

## Webhook Routing

Modify `_process_telegram_message` flow:

1. Extract `reply_to_message.message_id`.
2. Extract tagged text or reply text.
3. If it is a reply and contains `Status:`, try case update routing first.
4. If update routing succeeds, return a command-style result with reply text.
5. Otherwise continue normal complaint/command processing.

Pseudo-flow:

```python
reply_to_id = str(message_data.get('reply_to_message', {}).get('message_id', ''))
content = _extract_tagged_message_content(message_data)

if reply_to_id and _looks_like_status_update(content):
    result = handle_case_status_reply(
        group_id=group_id,
        reply_to_telegram_message_id=reply_to_id,
        update_telegram_message_id=telegram_message_id,
        sender=sender,
        content=content,
    )
    if result:
        return result
```

Important UX choice:

- For complaint creation, keep requiring the bot tag.
- For status replies, consider allowing untagged replies if they are replies to a known case and start with `Status:`.

Allowing untagged `Status:` replies is more natural:

```text
Status: resolved - relocated jiko
```

But it must be limited to replies to known case messages, otherwise normal group chatter could trigger updates.

## Case Lookup Logic

Lookup order:

1. `ParsedMessage.processed_message.raw_message.telegram_message_id == reply_to_id`
2. `ParsedMessage.source_telegram_message_id == reply_to_id`
3. If no match, check explicit `/update MSG_ID ...`
4. If multiple matches, ask staff to specify the case ID

Single match:

- update it

No match:

- reply: `I could not find the case connected to that message. Use /update MSG_ID Status: ...`

Multiple matches:

- list candidates and ask for `/update MSG_ID Status: ...`

## Batch Message Problem

If one Telegram message contains two or more cases and staff reply to that message:

```text
Status: resolved
```

the bot cannot know which case was resolved.

Options:

1. Ask staff to use `/update MSG_ID Status: ...`
2. Allow update text to include phone or customer ID:

```text
Status: resolved 0720809218 - jiko relocated
```

3. Bot replies with candidate cases:

```text
This message created 3 cases. Which one should I update?
1. MSG_A - Henry Mwenda - 0720809218
2. MSG_B - Mary Wanjiku - 0712345678
Reply: /update MSG_A Status: resolved - details
```

Recommended v1: ask for `/update MSG_ID` when ambiguous.

## Explicit Command Fallback

Add:

```text
/update MSG_ID Status: resolved - pipe replaced
```

Examples:

```text
@hb_biogas_cases_bot /update MSG_9A3F12 Status: resolved - jiko relocated
@hb_biogas_cases_bot /update MSG_9A3F12 Status: not reachable - phone off
@hb_biogas_cases_bot /update MSG_9A3F12 Status: scheduled - visit on Thursday
```

This should work whether or not it is a reply.

## Implementation Plan

### Phase 1 - Minimal Reliable Version

1. Add `CaseUpdate` model.
2. Add optional `source_telegram_message_id` and `batch_index` to `ParsedMessage` or `RawMessage`.
3. Add `case_update_parser.py`.
4. Add `GoogleSheetsService.update_case_row()`.
5. Add reply-to-original-message detection in `core/api/views.py`.
6. Add `/update MSG_ID Status: ...` fallback in `core/services/commands.py`.
7. Add tests for:
   - single case reply update
   - untagged `Status:` reply to known case
   - explicit `/update`
   - ambiguous batch reply
   - sheet row not found

### Phase 2 - Better UX

1. Bot lists candidate cases for ambiguous batch replies.
2. Add `risk:` and `loan risk:` parsing.
3. Add `/updates MSG_ID` to show update history.
4. Add `/reopen MSG_ID reason`.
5. Add retry job for pending sheet updates.

### Phase 3 - Analytics

1. Track time-to-resolution from `Date Reported` to `Date Resolved`.
2. Report stale cases with no updates.
3. Summarize closed/open/in-progress counts by region.
4. Show staff update activity.

## Test Cases

### Reply to Original Case Message

Original:

```text
@hb_biogas_cases_bot Henry Mwenda
24289449
0720809218
Requesting for a jiko relocation
```

Reply:

```text
Status: resolved - jiko relocated successfully
```

Expected:

- find original case by Telegram reply ID
- update `Status = Closed`
- append resolution details
- set `Date Resolved = today`
- update matching sheet row by `message_id`

### Not Reachable

```text
Status: not reachable - called 3 times, phone off
```

Expected:

- `Status = Open`
- `Date Resolved` remains blank
- resolution/note appended

### Scheduled

```text
Status: scheduled for Thursday
```

Expected:

- `Status = In Progress`
- `Date Resolved` remains blank
- note appended

### Ambiguous Batch

One Telegram message created 3 cases. Staff replies:

```text
Status: resolved
```

Expected:

- no sheet update
- bot asks for `/update MSG_ID Status: ...`

## Risks

### False Updates

If status detection is too loose, normal group chat could update cases. Mitigation: require reply-to-known-case plus `Status:`.

### Wrong Case Updated

Most likely with batch messages. Mitigation: if more than one case links to the same original message, do not guess.

### Sheet Update Failure

If the DB updates but Sheets fails, backend and sheet diverge. Mitigation: write to sheet first or mark update as pending and retry.

### Resolution Overwrite

Replacing `Resolution Details` can erase previous notes. Mitigation: append with timestamp/sender.

### Status Dropdown Mismatch

If sheet validation allows only specific statuses, bot must write only those exact values.

## Recommendation

Implement the strict version first:

- Staff reply to original case message.
- Reply must start with `Status:`.
- Single linked case updates automatically.
- Ambiguous batch messages require `/update MSG_ID`.
- Bot only updates `Status`, `Resolution Details`, and `Date Resolved`.
- Sheet update must succeed or the bot should say it is pending/failed.

This gives the team a natural workflow without making the parser guess too much.
