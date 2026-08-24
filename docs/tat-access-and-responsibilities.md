# TAT Access, Responsibilities, Escalations, and Private Alerts

## Purpose

This is the canonical administrator and developer guide for deciding:

- who may open and act on each TAT stage;
- who receives a pending-stage task first;
- when ranked backups are privately notified;
- how private Telegram alerts are connected and tested; and
- how conflicting or incomplete configuration is diagnosed.

The central rule is:

> Access grants authorize actions. Stage policy identifies the required role.
> Responsibility rosters route tasks. Private-alert status only determines
> whether Telegram can reach an otherwise eligible person.

These are deliberately separate controls. Adding someone to a responsibility
roster never gives them permission to act.

For the private task lifecycle and security details, also see
[TAT Private Tasks and Telegram Alerts](tat-private-tasks.md). The architecture
decision is recorded in
[ADR 0026](adr/0026-tat-access-and-responsibility-separation.md).

## Source-of-truth model

| Question | Authoritative source | What it does not do |
|---|---|---|
| May this user act in TAT? | Active `AccessGrant` for `tat_tracker`, matching role and scope | Does not make the user the preferred recipient |
| Which role owns this stage? | Canonical TAT product/stage configuration and capability policy | Cannot be replaced by typing a different role into a roster |
| Who receives the task first? | Active `TatResponsibilityAssignment` and ranked backups | Does not grant access |
| When is a backup alerted? | Active `TatEscalationRule` plus the backup's selected threshold | Does not change stage permission |
| Can Telegram deliver privately? | `UserProfile.telegram_id` and `TatPrivateAlertConnection` | Does not authorize the user |
| What happened? | TAT events, responsibility events, task recipients, delivery attempts, and configuration-request history | Audit evidence is not an editable workflow state |

Django/PostgreSQL owns this state. Google Sheets is not an access-control or
routing authority.

## Where to configure it

The main Superuser workspace is available in Django Admin at either:

- **TAT Tracker > Access & responsibilities**; or
- **Configuration > TAT access & responsibilities**.

The workspace combines the information needed to make a routing decision while
keeping the underlying records separate. It shows:

- workflow-group, branch, and product selectors;
- default role rosters;
- eligible staff and their exact access scope;
- private-alert connection status;
- canonical stage ownership and stage-specific overrides;
- configuration warnings; and
- the underlying responsibility records.

Useful linked Admin surfaces are:

- **Users**: edit a user and manage the **Access grants** inline;
- **Stage permissions**: inspect the TAT role/capability matrix;
- **TAT responsibility audit**: read append-only responsibility changes;
- **TAT private tasks**: inspect pending, acted, or superseded tasks;
- **TAT private alert connections**: inspect Telegram reachability;
- **TAT delivery exceptions**: inspect unresolved private-delivery failures;
- **TAT escalation rules**: inspect the currently approved rules; and
- **Workflow configuration requests**: inspect maker-checker changes to TAT
  targets, calendars, and escalation rules.

Only an active Django Superuser can directly maintain responsibility rosters.
A Superuser retains technical break-glass authority, but is not automatically
included in routine TAT notifications. Give the Superuser an explicit TAT
`AccessGrant` only if that person should also receive operational work.

## Understanding multi-role users

One user may hold several active TAT roles. Store each role and scope as its own
`AccessGrant`; do not combine roles in free text and do not create a duplicate
user account.

Example:

| User | Workflow | Role | Branch | Product | Group |
|---|---|---|---|---|---|
| Jane | TAT Tracker | Finance | Corporate | All products | JBL TAT Tracker |
| Jane | TAT Tracker | Secretary | Corporate | Business | JBL TAT Tracker |

When a Finance-owned stage becomes pending, only Jane's Finance grant is
considered. When a Secretary-owned Business stage becomes pending, only her
Secretary/Business grant is considered. The task records the exact acting role.
Her two grants remain independently activatable, reviewable, and revocable.

The current case stage resolves the role before a recipient is selected. The
system does not ask the user to choose which of their roles to use for that
task.

## Scope rules

An `AccessGrant` contains a workflow, role, and optional branch, product, and
workflow-group scope:

- blank branch means all permitted branches;
- blank product means all permitted products;
- blank group means all compatible configured groups; and
- a populated value restricts the grant to that exact scope.

A responsibility assignment always requires a workflow group, branch, role,
and primary user. Product and stage are optional:

- blank product means a roster for all products in that branch;
- blank stage means the default roster for that role; and
- a selected stage creates an override for that exact stage scope.

For an all-products responsibility roster, select people with all-products
grants. A product-limited grant must not be used as the primary for a roster
that routes other products.

Only active users with an active, matching TAT grant are eligible. Group,
branch, product, and role are rechecked when the task is created, delivered,
opened, and acted on. Deactivated, expired, or out-of-scope users are excluded
from routine routing. If a saved responsibility becomes invalid, the workspace
shows a configuration warning and task creation falls back safely.

## Routing precedence

For a pending stage, the service resolves one active responsibility from most
specific to least specific:

1. product-and-stage override;
2. all-products stage override;
3. product-specific role roster;
4. all-products role roster;
5. all eligible users in the required role as a shared-role fallback; then
6. a discoverable unassigned/delivery-exception task if nobody is eligible.

The database prevents two active rows with the same exact scope. If legacy or
unexpected data still produces more than one match at the winning specificity,
routing fails closed to the shared-role fallback rather than choosing a person
arbitrarily.

A recipient appearing through overlapping grants or roster entries is included
only once per task.

## Recommended setup sequence

Configure authorization before responsibility. This prevents a roster from
referring to a person who cannot perform the action.

### 1. Verify the TAT workflow group

1. Open **Workflow groups** in Django Admin.
2. Open the enabled group whose workflow type is **TAT Tracker**.
3. Confirm its branches and products are correct.
4. Set **TAT notification delivery** to **Shadow inbox** for initial validation.
5. Save the group.

The delivery modes are:

| Mode | Durable inbox tasks | Private Telegram messages | Existing detailed group alerts |
|---|---:|---:|---:|
| Existing group alerts | No | No | Yes |
| Shadow inbox | Yes | No; records what would have been sent | No private delivery |
| Private inbox and Telegram alerts | Yes | Yes | Only cumulative privacy-safe delivery exceptions |

Use Shadow first. Do not enable real Telegram delivery while configuration
warnings remain.

### 2. Verify the staff identity

1. Open **Users** and select the staff member.
2. Confirm the account is active.
3. Confirm the staff profile is linked to the correct Telegram identity.
4. Do not copy real identifiers into test fixtures or documentation.

### 3. Add every required access role

1. On the same user page, find **Access grants**.
2. Add an active grant with:
   - **Workflow**: TAT Tracker;
   - **Role tag**: the role the person performs;
   - **Branch**: one branch, or All branches;
   - **Product**: one product, or All products; and
   - **Group configuration**: the exact TAT group, or All compatible groups.
3. Save the user.
4. Repeat with another grant when the same person has another role or scope.
5. Use **View effective access** to confirm the resulting capabilities and
   exact authorizing scopes.

The role selector is governed. Use the canonical role offered by the Admin;
do not invent a new spelling or encode multiple roles in one value.

### 4. Verify stage ownership and capabilities

1. Open **TAT access & responsibilities**.
2. Select the workflow group, branch, and optional product.
3. Review **Canonical stage ownership**.
4. Use **Stage permissions** to inspect the capability associated with a role.

The stage definition owns the responsible role. Selecting a stage in a
responsibility form automatically derives and locks its role. If ownership is
wrong, correct the governed stage/capability configuration; do not work around
it by routing the stage under an unrelated role.

### 5. Configure escalation thresholds

Escalation thresholds are high-impact workflow configuration and use
maker-checker approval.

1. A user with `tat.settings.escalation.propose` opens the TAT Mini App.
2. Open **Settings > Overdue escalation**.
3. Add or edit threshold percentages, routing roles, and optional branch scope.
4. Enter a reason and select **Propose escalation change**.
5. A different authorized user with `tat.settings.escalation.approve` reviews
   and approves or rejects the proposal.
6. Confirm the approved rows under **TAT escalation rules** in Django Admin.

Thresholds are percentages of the pending stage's frozen SLA target. For
example, 100% is the target boundary and 150% is one-and-a-half times the
target. A responsibility backup can select only a currently active threshold
applicable to its branch.

### 6. Connect private Telegram alerts

Each staff member completes this step for their own account:

1. Start the JBL bot in a private Telegram chat.
2. Open the TAT Mini App.
3. Open **Settings**.
4. Under **Private alerts**, tap **Connect private alerts**.
5. Confirm that the bot sends the connection test message.

Django marks the connection as connected only after Telegram accepts that test
message. If Telegram cannot reach the user, confirm the staff profile mapping,
ask the user to start/unblock the bot, and retry from the Mini App.

### 7. Create a default role roster

1. Return to **TAT access & responsibilities**.
2. Select the correct workflow group, branch, and optional product.
3. Under **Default role rosters**, select **Assign roster** for the required
   role.
4. Choose the primary user.
5. Enter a required operational reason.
6. Set the effective start and optional end time.
7. Add backups only when required:
   - rank 1 is the first backup;
   - each user must have a matching active grant;
   - select an approved SLA threshold; and
   - every later rank must use a strictly later threshold.
8. Save.

The eligible-user selector is intentionally filtered. If a person is missing,
fix their `AccessGrant`; do not weaken the roster validation.

### 8. Add a stage override only when necessary

Most stages should use their role's default roster. Use an override when one
specific stage or product needs a different primary.

1. In **Canonical stage ownership**, find the stage.
2. Select **Add override**.
3. Confirm the prefilled group, branch, product, and stage.
4. Confirm that Role is derived and locked.
5. Choose an eligible primary and optional ranked backups.
6. Enter the reason and save.

Avoid creating an override for every stage when a single role roster expresses
the operating model correctly.

### 9. Clear configuration warnings

The workspace can report:

- unknown stage keys;
- a stored role conflicting with canonical stage ownership;
- an active assignment whose end time has passed; or
- a primary who no longer has matching active access.

Open every warning, correct or deactivate the row, and enter a clear reason.
Migration `0127_tat_responsibility_canonical_routing` deliberately deactivates
conflicting or unknown legacy stage rows instead of silently changing their
meaning.

## Backup and delivery behavior

The primary recipient receives the initial prompt. Backups receive inbox
visibility when the task is created, but their Telegram messages are scheduled
by rank and threshold.

If the primary is already known to be unconnected, blocked, or otherwise
unreachable, the first reachable backup is tried immediately. If that backup
is unreachable, the next ranked backup is tried without waiting for a later
threshold. If nobody can be reached, Django keeps the task discoverable and
maintains one cumulative, privacy-safe group exception per role rather than
posting customer details or one group message per case.

Task completion is idempotent. The first valid stage completion closes or
supersedes all recipient copies. A stale Telegram link cannot stamp an old case
revision.

## Safe test procedure

Use synthetic users and a Pilot TAT cycle. Never test with customer data or a
production Telegram group.

### Shadow test without Telegram delivery

1. Set the workflow group to **Shadow inbox**.
2. Create synthetic users with the intended multi-role access combinations.
3. Create default rosters, an override, and ranked backups.
4. Create or advance a synthetic Pilot case until the target stage is pending.
5. Open the users' TAT inboxes and verify:
   - the stage selected the correct role;
   - the intended primary and backups appear once;
   - a user with another unrelated role is not included; and
   - delivery state records Shadow rather than sending Telegram messages.
6. Change the case revision and confirm the earlier task becomes superseded.

### Controlled private-message test

This step causes an external Telegram side effect. Perform it only in an
authorized test environment with synthetic accounts.

1. Connect the synthetic primary and backup through **Connect private alerts**.
2. Change only the synthetic workflow group to **Private inbox and Telegram
   alerts**.
3. Create one synthetic Pilot task.
4. Confirm the primary receives exactly one private message.
5. Open the deep link and confirm it opens the exact pending stage but does not
   mutate state merely by opening.
6. Complete the stage and verify one TAT event, one acted task, and no duplicate
   update after a repeated tap.
7. Repeat with the primary marked unconnected and confirm the first reachable
   backup is prompted immediately.
8. For scheduled backup testing, advance the controlled clock or use a short
   approved test target, then run:

```powershell
.\.venv\Scripts\python.exe manage.py process_tat_notifications --limit 100
```

9. Return the test group to Shadow or its approved operating mode.

In production, schedule `process_tat_notifications` at least once per minute so
due retries and backup thresholds are processed promptly.

## Developer verification

Run the narrow behavior tests first:

```powershell
.\.venv\Scripts\python.exe manage.py test core.tests_tat_notifications core.tests_tat_tracker
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

Run the responsive Django Admin audit with synthetic data:

```powershell
.\scripts\verify_admin_ui.ps1 -Viewport phone-320
.\scripts\verify_admin_ui.ps1 -Viewport desktop-1440
```

The Admin audit creates a temporary SQLite database and synthetic records. It
must not point at production. The separate Mini App visual audit requires a
running synthetic server:

```powershell
.\scripts\verify_tat_private_tasks_ui.ps1
```

## Troubleshooting

| Symptom | Likely cause | Resolution |
|---|---|---|
| User is missing from Primary user or Backup | No active TAT grant matches role, group, branch, and product | Correct the user's AccessGrant, save, then reload the responsibility form |
| User can act but receives no routine task | Authorization exists, but no matching roster won or the user is not a recipient | Check precedence, effective dates, and the selected group/branch/product |
| User is routed but action is denied | Grant or capability changed after task creation, or scope/revision is stale | Inspect effective access and current stage; do not bypass the recheck |
| Role becomes locked after choosing a stage | Expected behavior; stage policy owns the role | Change stage policy through its governed process if ownership is actually wrong |
| Backup threshold dropdown is empty | No active approved TAT escalation rule exists | Propose and independently approve escalation rules first |
| Backup threshold is rejected | It does not apply to the branch or is not later than the preceding rank | Select an applicable active threshold in strictly increasing order |
| Private alert says Unknown or Never connected | User has not completed the private test delivery, or lacks a Telegram mapping | Start the bot, verify the profile, and tap Connect private alerts |
| Private alert says Blocked | Telegram returned a permanent delivery failure | Ask the user to unblock/start the bot, then reconnect |
| Task goes to the whole role | No valid unique responsibility assignment won | Add or repair the default role roster; review configuration warnings |
| Delivery exception appears in the group | No eligible recipient was privately reachable | Repair access/roster/connection; the task remains discoverable in Admin |
| Same person appears to have multiple roles | Expected when several grants exist | Review each grant independently; the stage chooses the relevant one |
| Legacy assignment is inactive after migration | Its stage was unknown or its saved role conflicted with canonical ownership | Review it in the workspace and replace it with a valid roster or override |

## Audit and change-management rules

- Every responsibility create or update requires a reason.
- Responsibility changes create append-only `TatResponsibilityEvent` records
  with before/after snapshots.
- Deactivation is preferred when retaining operational history is useful.
- A Superuser deletion remains audit-recorded, but should not be used to hide a
  configuration mistake.
- Capability and escalation changes retain their independent maker-checker
  evidence.
- Assignment never implies permission, even for a Django Superuser.
- Do not edit task, recipient, delivery, or audit rows to force a workflow
  outcome. Correct the configuration and let the services reconcile state.

## Migration and rollback

Apply the schema migration through the normal release process:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

Migration `core.0127_tat_responsibility_canonical_routing`:

- adds the append-only responsibility-event table;
- preserves role-level rosters;
- deactivates only conflicting or unknown legacy stage routes for review; and
- does not change access grants, TAT cases, Sheets, Drive, or Telegram.

After migration, review every warning in **TAT access & responsibilities**
before enabling private delivery.

For a non-production rollback before the new audit records are relied upon:

```powershell
.\.venv\Scripts\python.exe manage.py migrate core 0126_tatprivatealertconnection_and_more
```

Do not reverse the migration after responsibility events have become
operational evidence. Prefer restoring application code while retaining the
audit table. Applying or reversing a production migration requires separate,
explicit release approval.

## Developer ownership map

| Area | Primary implementation |
|---|---|
| Shared workflow authorization | `core/models.py` (`AccessGrant`), `core/services/access_policies.py`, and `core/services/access_control.py` |
| Role/capability policy | `core/services/workflow_capabilities.py` |
| TAT stage definitions and transitions | `core/services/tat_tracker.py` |
| Canonical responsibility validation | `core/services/tat_responsibilities.py` |
| Task routing, inbox, locators, delivery, and escalation | `core/services/tat_notifications.py` |
| Escalation maker-checker flow | `core/services/miniapp_settings.py` |
| Admin workspace and forms | `core/admin.py` and `core/templates/admin/core/tatresponsibilityassignment/` |
| Mini App settings and inbox UI | `core/templates/tat_tracker/` and `core/static/miniapp/tat_tracker.js` |
| Focused behavior tests | `core/tests_tat_notifications.py` and `core/tests_tat_tracker.py` |

Keep responsibility routing TAT-specific. `AccessGrant` is intentionally shared
across workflows, but Origination review ownership, SPIN review, Portal queues,
and Complaint Cases must not be forced into TAT's ranked-stage roster model.
