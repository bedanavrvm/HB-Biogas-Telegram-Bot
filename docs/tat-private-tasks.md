# TAT Private Tasks and Telegram Alerts

## Purpose

Routine TAT stage alerts can be routed to individual staff instead of filling the workflow group. Django remains the source of truth: the Mini App task inbox is durable, while Telegram only delivers a private prompt and an authenticated deep link.

Telegram buttons never stamp a case directly. They open the exact pending stage, where the current user, access grant, case revision, and stage permission are checked again before confirmation.

## Rollout modes

Open **Django Admin → Workflow groups**, select the TAT group, and use **TAT notification delivery**:

- **Existing group alerts** preserves the previous detailed group messages.
- **Shadow inbox** creates tasks and records `would_send` routing decisions without calling Telegram.
- **Private inbox and Telegram alerts** enables private messages, ordered backup escalation, and the cumulative privacy-safe group exception.

Start with Shadow. Review responsibility mappings and private-alert connection status before changing a group to Private inbox and Telegram alerts.

## Configure responsibility routing

1. Create the required TAT `AccessGrant`s first. An assignment routes work but never grants permission.
2. Open **Django Admin → Configuration → TAT responsibility routing**.
3. Select the TAT workflow group, branch, and role.
4. Optionally restrict the mapping to one product and/or one stage. Blank product and stage values cover the whole branch-role scope.
5. Choose the primary actor.
6. Add ordered backups. Each backup needs a rank and a percentage that matches an active TAT escalation rule for the branch.
7. Save and correct every validation warning before enabling Hybrid mode.

Routing uses the most specific active match: branch/role/product/stage, then branch/role/stage, branch/role/product, and finally branch/role.

The primary receives the initial private prompt. Backups see the work immediately in their Mini App inbox, but receive private prompts only at their configured SLA thresholds. If a primary is known to be unreachable, the first reachable backup is prompted immediately.

## Connect a staff member's private alerts

The staff account must already have a canonical `UserProfile.telegram_id` and a matching TAT `AccessGrant`.

1. The staff member starts the JBL bot in a private Telegram chat.
2. They open the TAT Mini App and go to **Settings**.
3. Under **Telegram task alerts**, tap **Connect private alerts**.
4. Telegram asks for private write access where supported.
5. Django sends a private test message and records the connection only after successful delivery.

An unconnected or blocked primary is immediately soft-escalated; the system does not wait for an impossible delivery attempt to consume the SLA window.

## Staff task flow

1. The private Telegram message contains minimal operational context and **Open TAT task**.
2. The button opens the exact case and pending stage.
3. Timestamp stages show a compact **Confirm stamp** sheet.
4. Choice stages show only the permitted outcomes and a confirmation action.
5. The update goes through the existing revision-aware and idempotent TAT transition service.
6. After success, the actor can open the next task directly.

If another actor already completed the stage, or the case revision changed, the old task is marked acted or superseded. Opening an old link shows the current safe state and opens the replacement task only when the user remains authorized.

## Delivery operations

Run due retries and backup escalations with:

```powershell
.\.venv\Scripts\python.exe manage.py process_tat_notifications --limit 100
```

Schedule this command at least once per minute in production so SLA threshold alerts are prompt. Immediate task creation still performs an after-commit delivery attempt; the command covers transient retries and future backup thresholds.

Use these Admin views for support:

- **TAT private tasks**: current, acted, and superseded tasks plus recipient state.
- **TAT private alert connections**: connected, blocked, unknown, or temporarily failing users.
- **TAT delivery exceptions**: cumulative unreachable counts by workflow group and role.
- **TAT responsibility routing**: primary and backup configuration.

A Superuser is not added to operational recipient lists automatically. They can still discover orphaned work in Admin, repair the responsibility mapping, and use existing audited technical override capabilities.

## Privacy and security

- Private messages contain no phone number, national ID, amount, or applicant name.
- Task tokens contain 192 random bits and are encoded as 32 URL-safe characters.
- Only token hashes are stored.
- Locators expire after 72 hours and are revoked on completion, cancellation, or supersession.
- A valid locator is not authorization. Telegram `initData`, current `AccessGrant`, scope, stage capability, task state, and workflow revision are all verified server-side.
- Group exceptions contain only the role, unresolved count, and age of the oldest task.

## Verification checklist

- Confirm Shadow mode resolves the intended primary and backups for representative branch/product/stage combinations.
- Confirm users without matching grants are rejected from assignments.
- Connect one synthetic Telegram account and verify the private test message.
- Create a synthetic TAT case and confirm exactly one private prompt is sent.
- Confirm the deep link opens the correct case and compact confirmation sheet.
- Double-tap confirmation and verify only one workflow event is created.
- Mark a primary unconnected and confirm the first reachable backup is prompted immediately.
- Advance the SLA clock and run `process_tat_notifications`; verify ranked backup delivery.
- Open an old locator after the case revision changes and verify it cannot stamp stale state.
- Create two unreachable synthetic tasks and confirm the single group exception shows a cumulative count of two.
- Do not use real customer details or production Telegram groups during testing.
