# TAT Tracker Mini App User Guide

## About this guide

This non-technical guide explains how staff use the TAT Tracker Mini App. It
covers its screens, role-based actions, timers and statuses, reports, Google
Sheets synchronization, and troubleshooting.

Screens and buttons are permission-aware. A user sees only the work, branches,
products, and actions assigned to them. A missing button is therefore not
automatically an application fault.

> **Screenshot safety:** Use synthetic training information in every screenshot.
> Never capture a real name, phone number, national ID, amount, Telegram
> identity, access token, private message, or production Sheet for this guide.

## Contents

1. [What the Tracker does](#1-what-the-tracker-does)
2. [Roles and access](#2-roles-and-access)
3. [Opening the Mini App](#3-opening-the-mini-app)
4. [The case queue](#4-the-case-queue)
5. [Creating a case](#5-creating-a-case)
6. [Finding a case](#6-finding-a-case)
7. [Case detail](#7-case-detail)
8. [Completing stages](#8-completing-stages)
9. [Remarks and activity](#9-remarks-and-activity)
10. [Correcting a case](#10-correcting-a-case)
11. [Settings and private alerts](#11-settings-and-private-alerts)
12. [Governed configuration](#12-governed-configuration)
13. [Pilot and Production](#13-pilot-and-production)
14. [TAT Reports](#14-tat-reports)
15. [Downloading reports](#15-downloading-reports)
16. [Google Sheets synchronization](#16-google-sheets-synchronization)
17. [Telegram batch intake](#17-telegram-batch-intake)
18. [Good working practices](#18-good-working-practices)
19. [Errors and troubleshooting](#19-errors-and-troubleshooting)
20. [Quick reference](#20-quick-reference)
21. [Screenshot checklist](#21-screenshot-checklist)

---

## 1. What the Tracker does

TAT means **Turnaround Time**. The Mini App tracks one loan case through the
stages that apply to its product, requested amount, and approved workflow
version.

It helps staff answer:

- Which cases are ready for my role?
- What action is required next?
- How long has the case or current stage taken?
- Is it within target, near target, or overdue?
- Who recorded or corrected each action, and when?
- Which active cases need management attention?

Each case receives a human-readable reference such as `JBL-BS-2026-001`. Use
this reference when searching or requesting support.

### The case journey

1. An authorized user creates a loan case.
2. The applicable product and stage configuration is frozen for that case.
3. Each stage becomes actionable only for its responsible role and after its
   prerequisites are satisfied.
4. Staff record stage stamps or controlled outcomes.
5. The Tracker records elapsed time, target position, remarks, corrections,
   and audit history.
6. The case finishes as **Disbursed** or **Declined**.

Products do not necessarily have the same stages. Requested amount can also
select a different governed loan-cycle path. Always follow the stages displayed
on the case rather than a remembered generic list.

### Business benefit

The Tracker provides one current operational view, reduces informal follow-up,
prevents out-of-order approvals, makes delays visible, and retains evidence of
every action and correction.

> **Screenshot 1 — Tracker overview**
>
> ![TAT Mini App screenshot 1: 01 tracker overview](docs/images/tat/01-tracker-overview.png)

---

## 2. Roles and access

Telegram sign-in proves who opened the app. It does not itself grant workflow
access. The user also needs an active TAT assignment for the relevant group,
branch, product, and role.

| Role | Typical responsibility |
|---|---|
| BRO | Creates cases and completes BRO stages. May correct permitted case details. |
| Head of Rural | Completes configured business-administration stages, may create cases, and reviews governed configuration proposals. |
| CA | Completes Credit Analysis stages. |
| BM | Completes Branch Manager stages and responses. |
| Secretary | Records scheduled/held meetings and shared minutes where applicable. |
| Chair | Records the governed committee decision where applicable. |
| Loan Approver | Records sanctions or register approval where applicable. |
| Finance | Records final disbursement. |
| Management | Views authorized cases and reports. |
| IT | Has technical override capabilities within assigned scope, including reports and audited corrections. |

Access controls which cases, branches, and products appear; whether **Create**,
**Find**, or **TAT Reports** appears; which stage can be completed; which
corrections are allowed; and which configuration controls appear in Settings.
Filters can narrow access but never expand it.

If an expected control is missing, confirm the case stage and your role. Then
contact the JBL administrator with the case reference, role, branch, and
product. Do not send customer identifiers in a support chat.

### Business benefit

Role and scope controls protect customer information and prevent staff from
performing an action outside their responsibility.

---

## 3. Opening the Mini App

Open the Tracker from the approved Telegram bot or group launcher. In a
configured group, use:

```text
@your_bot /tat
```

Tap **Open TAT Tracker Mini App**. The app then verifies the Telegram launch,
resolves the staff account and current access policy, loads permitted products
and branches, and opens the user's permitted preferred start screen.

The header shows the user's name and TAT roles. Use **Refresh** after a long
pause or before an important stage action.

### Private task links

When private alerts are connected, the bot can send a direct assigned-stage
link. The app opens the current case and highlights the stage when it remains
actionable.

A link may be expired or superseded because the case advanced, the task was
rerouted, another user acted, or access changed. Open the current case from the
queue rather than trying to force the old task.

### Business benefit

Telegram launch ties actions to an identified staff account, while private
links route work without exposing customer details in group messages.

> **Screenshot 2 — Verified header after launch**
>
> ![TAT Mini App screenshot 2: 02 telegram launch](docs/images/tat/02-telegram-launch.png)

---

## 4. The case queue

The **Cases** workspace is the main daily working area.

### Ready for my role

This queue contains cases whose next governed stage can be performed by one of
the user's current roles and scopes. It can include a case whose first private
alert went to another eligible colleague because the queue reflects current
authorization, not just message delivery.

### All cases

This shows every case the user is permitted to view, including cases waiting
for another role. It does not mean every case in the organization.

### Cards, filters, and pages

A card can show the reference, customer, product, branch, amount, status, next
action, TAT, and updated time. Tap it to open the case.

Use **Filters** to narrow by available product, branch, or status. Applied
filters appear as removable pills. Counts and pagination apply to the selected
queue and filters. Use **Reset** to clear the filter selection.

Use **Previous** and **Next** when more pages are available. The freshness line
states when the queue was last confirmed. If a background refresh fails, the
app retains the last confirmed queue rather than showing an unverified empty
list.

In Settings, **Use compact case cards** keeps essential worklist information on
the card and leaves identifiers and timestamps for the detail screen.

### Business benefit

Separating actionable work from the broader in-scope list reduces scanning
time while retaining access to the operational context.

> **Screenshot 3 — Ready for my role and All cases**
>
> ![TAT Mini App screenshot 3: 03 case queues](docs/images/tat/03-case-queues.png)
>
> **Screenshot 4 — Queue filters and active pills**
>
> ![TAT Mini App screenshot 4: 04 queue filters](docs/images/tat/04-queue-filters.png)

---

## 5. Creating a case

**Create** appears only for authorized users. It starts a new loan journey; it
must not be used to repair an existing case.

### Required information

| Field | What to enter |
|---|---|
| Product | The product for the new loan. Only available products appear. |
| Branch | The branch responsible for the loan. |
| Client Name | The full customer name. It is stored in capital letters. |
| ID Number | A digits-only National ID / Maisha Namba containing 1–9 digits. Do not enter the card serial number. |
| Phone Number | A valid Kenyan phone number. |
| BRO Name | The responsible BRO. A BRO creator may default to themselves. |
| Requested amount (KES) | A whole-KES amount within the product's permitted range. |

The product can add required evidence, custom information, tenor, or optional
fee choices. These fields come from the governed product version.

Select the product before entering the amount so the form can show the relevant
range. The server rechecks product availability, scope, amount, evidence,
custom values, and fees on submission.

### Existing-loan warning

After a sufficiently complete ID or phone is entered, the app may show prior
accessible loans found on those details. This is context, not an automatic
duplicate rejection: one customer can have separate loans. Open the prior case
if the intention was correction; continue only for a genuinely separate loan.

### Submit safely

1. Review product, branch, identity, BRO, and amount.
2. Complete product-specific requirements.
3. Tap **Create new loan case** once.
4. Wait for **Case created. Continue from the highlighted stage.**

The same submission retains a stable request reference for safe retry. If the
result is uncertain, refresh and use **Find** before submitting again.

Creation is confirmed only after the configured primary creation/publication
path succeeds. An error does not justify blindly creating another case.

### Business benefit

Creation validation prevents invalid identities, inaccessible locations,
out-of-range amounts, missing requirements, and accidental correction by
duplicate creation.

> **Screenshot 5 — Create new loan case**
>
> ![TAT Mini App screenshot 5: 05 create case](docs/images/tat/05-create-case.png)
>
> **Screenshot 6 — Existing-loan context**
>
> ![TAT Mini App screenshot 6: 06 existing loan context](docs/images/tat/06-existing-loan-context.png)

---

## 6. Finding a case

**Find** appears for users with search access. Search by part or all of a case
reference, customer name, national ID, phone, branch, or BRO.

Results are restricted to the user's scope and to a bounded set of the most
recently updated matches. The exact case reference is therefore the best
search. Tap a result to open it.

If a case does not appear, check the spelling and scope. Queue filters do not
control Find. Ask the administrator to check access if a known in-scope case
remains unavailable.

### Business benefit

Find gives staff operational lookup without requiring Sheet row numbers or
internal database identifiers.

> **Screenshot 7 — Find Case**
>
> ![TAT Mini App screenshot 7: 07 find case](docs/images/tat/07-find-case.png)

---

## 7. Case detail

The detail screen is the authoritative working view for one case.

### Summary

It shows customer name, case reference, product, branch, requested or final
amount, national ID, phone, status, next action, official wall-clock TAT,
created/updated times, and any current SLA escalation.

### Staff-facing statuses

| Status | Meaning |
|---|---|
| Active | Progressing through its governed stages. |
| Stalled | Active but at the configured overdue/stall condition. |
| Declined | Finished through a negative outcome such as rejection, deferral, unmet sanctions, or another terminal result. |
| Disbursed | Finance recorded successful disbursement. |

The exact negative outcome remains visible in the completed stage and timeline
even though staff reporting groups it under **Declined**.

### SLA states

| SLA label | Meaning |
|---|---|
| Within Target | Below the configured near-target threshold. |
| Near Target | At the warning portion of the target but not overdue. |
| Overdue | Beyond the applicable target. |
| Target Unavailable | No usable target exists; this does not mean within target. |

Counters use server-confirmed time. Active counters continue increasing;
terminal counters stop at the recorded terminal time.

### Read-only cases

A case is read-only when it belongs to a closed Pilot cycle or its legacy
configuration cannot yet be proven. It remains visible for reference, but
operational editing is blocked until the applicable administrative action.

### Business benefit

The summary displays the effective outcome and next step directly instead of
requiring users to calculate time or interpret raw configuration.

> **Screenshot 8 — Case summary and TAT status**
>
> ![TAT Mini App screenshot 8: 08 case summary](docs/images/tat/08-case-summary.png)

---

## 8. Completing stages

**Workflow Stages** shows the exact frozen path for the case. Each row shows
its label, responsible role, recorded value, time/target information, and
current action state.

- Checked means complete.
- Highlighted means actionable by the current user.
- Locked means it is waiting for prerequisites, belongs to another role, or is
  unavailable. Read the displayed reason.

### Timestamp stages

Tap **Stamp Approval** only when the named business event actually occurred.
The server records the authoritative time and actor.

### Outcome stages

Some stages require a controlled choice such as approved/declined or met/not
met. A choice can advance or terminate the workflow, so verify it before
saving. Negative terminal choices remain in history while the case status
becomes **Declined**.

### Final loan amount

At the configured BRO application stage, a successful outcome can require the
whole-KES amount actually applied on the loan system. The original requested
amount remains retained, and lowering the final amount does not change the
case's frozen loan-cycle path.

### Product requirements and certificates

A stage may display product-specific evidence or custom fields. Complete all
required controls before saving. Where a stage needs governed signing
evidence, its certificate status is displayed and missing evidence prevents
final satisfaction.

### Safe saving

The server checks revision, Pilot/Production version, role, scope, sequence,
prerequisites, product requirements, terminal state, and request identity.

If another user changed the case first, refresh, review the newer state, and
resubmit only when the action is still appropriate.

### Business benefit

Server-owned sequence and responsibility prevent premature approvals while the
screen makes the current effective action clear.

> **Screenshot 9 — Completed, actionable, and locked stages**
>
> ![TAT Mini App screenshot 9: 09 stage states](docs/images/tat/09-stage-states.png)
>
> **Screenshot 10 — Outcome and final amount**
>
> ![TAT Mini App screenshot 10: 10 stage outcome](docs/images/tat/10-stage-outcome.png)

---

## 9. Remarks and activity

Use **Remarks / Delays** for useful operational context: a missing document,
customer follow-up, blocking condition, or relevant delay. Write enough for
the next authorized user to understand, then tap **Save Remarks**.

Open **Activity** to see meaningful case events, recorded values, staff actor,
authority where relevant, date/time, and protected linked documents. Technical
duplicate receipts are omitted from the user timeline.

### Business benefit

Remarks support handover; append-only activity supports accountability and
investigation without silently replacing earlier evidence.

> **Screenshot 11 — Remarks and Activity**
>
> ![TAT Mini App screenshot 11: 11 remarks activity](docs/images/tat/11-remarks-activity.png)

---

## 10. Correcting a case

Corrections repair errors. They are not ordinary progression and do not erase
the original evidence.

### Correct case details

When authorized, **Correct case details** allows changes to customer name,
national ID, phone, branch, and BRO name. Change only incorrect values and tap
**Save correction**. Empty/no-change submissions are not recorded.

The default capability is available to scoped BRO, Head of Rural, and IT users,
subject to policy and case state.

### Correct a completed stage

Authorized IT users can see **Correct** on a completed stage and enter an
allowed replacement outcome or date/time. This is more restricted because it
can change timing evidence, status, reports, and later-stage meaning.

A successful correction advances the revision, records actor and old/new
values, refreshes derived metrics where required, and republishes the current
Sheet projection. If the case changed after opening the form, refresh first.

### Business benefit

Audited correction keeps records accurate without silent overwrites or
duplicate cases.

> **Screenshot 12 — Audited correction**
>
> ![TAT Mini App screenshot 12: 12 case correction](docs/images/tat/12-case-correction.png)

---

## 11. Settings and private alerts

### Work defaults

Users can choose **Start on** (Queue or Create case) and **Use compact case
cards**. Create is honored only for accounts with creation access. Tap **Save
my settings**; these choices affect only the current user's workspace.

### Telegram task alerts

After starting the bot privately, tap **Connect private alerts**. Status can be:

- **Connected:** direct assigned-task delivery is enabled.
- **Disconnected:** delivery is paused.
- **Blocked:** unblock/start the bot, then reconnect.
- **Temporary failure:** assigned work still exists, but delivery needs
  attention.

Disconnecting alerts does not remove the role or responsibility. The current
Mini App does not expose a separate task-inbox screen; **Ready for my role** is
the reliable in-app view of actionable work.

Settings also shows account/scope context, application release, data mode, and
any background-update warning.

### Business benefit

Personal settings improve daily use without changing shared rules. Private
alerts shorten response time without public customer details.

> **Screenshot 13 — Work defaults and private alerts**
>
> ![TAT Mini App screenshot 13: 13 settings alerts](docs/images/tat/13-settings-alerts.png)

---

## 12. Governed configuration

Ordinary users do not see configuration controls.

### Target proposals

Authorized IT users can propose stage targets in minutes. A total is optional;
if blank, applicable loan-cycle stage targets determine it. Every proposal
needs a reason and does not become live until a different authorized Head of
Rural approves it.

### Escalation proposals

Authorized IT users can propose a threshold percentage, recipient role, and
optional branch scope. Blank branch means general coverage; a named branch is
more specific. A reason and independent review are required.

### Reviews

An authorized reviewer can approve or reject a pending proposal they did not
make. A scoped IT override, where available, requires confirmation and an
audited reason. Configuration authority does not itself grant case access.

### Business benefit

Maker-checker review prevents one person from silently changing service
targets or escalation routing.

> **Screenshot 14 — Configuration proposal/review**
>
> ![TAT Mini App screenshot 14: 14 configuration review](docs/images/tat/14-configuration-review.png)

---

## 13. Pilot and Production

**Production** cases are live operational records and remain operational when
the workflow later enters Pilot mode.

A visible **Pilot** indication means new records belong to the current test
cycle. Do not treat them as production loans. When a Pilot cycle is rotated,
old cases remain for reference but become read-only and show **Closed Pilot
cycle**.

If the mode changes while a form is open, the server can reject the stale
write. Refresh, confirm the current mode, and review before continuing.

### Business benefit

Data modes prevent test records from being mistaken for live business while
retaining test-cycle evidence.

> **Screenshot 15 — Pilot/read-only state**
>
> ![TAT Mini App screenshot 15: 15 pilot mode](docs/images/tat/15-pilot-mode.png)

---

## 14. TAT Reports

**TAT Reports** appears for authorized Management and IT users. It is a scoped
live report over canonical TAT cases, not a Sheet editor.

### Current Workload

This view focuses on active pressure. Metrics can include Active, Within
Target, Near Target, Overdue, and Target Unavailable.

### Period Performance

This summarizes cases or completed stage actions for the selected period.
Metrics can include Created/Cases, Finished/Completed Actions, Disbursed,
Declined, SLA Met %, and median/percentile TAT. Read the metric labels: a
completed-stage-action view is not a count of finished loans.

### Filters and freshness

Filters can include search, branch, product, role, status/SLA, date range,
stage, comparison dimension/metric, and heatmap choices. The filter sheet marks
controls that affect, configure, or change the focused insight. A warning means
an active filter does not affect that chart; it may still affect the table or
another insight.

Freshness shows the latest reporting snapshot and pending/failed rebuild work.
A warning recommends review; it does not automatically mean every value is
wrong.

### Insights

Use **Carousel** for one insight with Previous/Next or swipe, or **List** for a
vertical set. Insights can include:

| Insight | Operational question |
|---|---|
| Workload over Time | How is active workload changing? |
| Case Stage Progression | Where did one selected case spend its time? |
| Current-stage Backlog Age | How old is active backlog? |
| SLA Compliance over Time | What proportion met target? |
| Median and P90 TAT | What is typical and slow-case performance? |
| Stage Performance Against Target | Which stages consume/exceed target? |
| Operational Comparison | How do selected dimensions compare? |
| Operational Heatmap | Where do two dimensions combine into pressure? |
| Target Review Signals | Which recurring delays deserve investigation? These do not change targets. |
| Oldest Active Cases | Which cases may need attention first? |

Where offered, switch line/bar/pie without changing the underlying data.

### Report table

The table can include reference, customer, group, branch, product, status,
stage, role, dates, elapsed/target/variance, SLA state, and stage TAT columns.

- Scroll horizontally on a phone.
- Use **Table size** controls; long values retain the normal grid font size.
- Press and hold a cell to copy its displayed value.
- Use **Previous** and **Next** for result pages.

Named-person performance appears only with the corresponding capability.

### Business benefit

Reports combine workload, outcomes, stage pressure, and case evidence without
manual calculation across several Sheet tabs.

> **Screenshot 16 — Current Workload**
>
> ![TAT Mini App screenshot 16: 16 current workload](docs/images/tat/16-current-workload.png)
>
> **Screenshot 17 — Report filters**
>
> ![TAT Mini App screenshot 17: 17 report filters](docs/images/tat/17-report-filters.png)
>
> **Screenshot 18 — Insights and table**
>
> ![TAT Mini App screenshot 18: 18 insights table](docs/images/tat/18-insights-table.png)
>
> **Screenshot 19 — Period Performance**
>
> ![TAT Mini App screenshot 19: 19 period performance](docs/images/tat/19-period-performance.png)

---

## 15. Downloading reports

Authorized users can tap **Download XLSX**. The workbook uses the active view
and filters and includes a case-level TAT Report, selected operational
comparison, and selected heatmap.

Exports are audited with actor, view, filters, fields, and row count. Generated
date/time values use the approved day-first format.

If more than 10,000 rows match, narrow the date range, branch, product, status,
or other filters. On a phone, keep the app open until the download begins,
allow Telegram/browser download access, and check Downloads before retrying.

### Business benefit

The workbook provides a controlled offline artifact with the same access and
filter boundaries as the live report.

---

## 16. Google Sheets synchronization

Django is the TAT workflow source of truth. Google Sheets is an operational
projection. Never use manual cell edits to change case identity, stages,
status, or timing; use authorized Mini App actions.

### Published information

Depending on schema, a row can include case reference, customer identity,
branch, BRO, product, amount, created time, stage stamps/outcomes, status,
remarks, final amount, TAT, and updated information. The immutable reference is
used to resolve the row so retry updates the same case.

### Creation publication

New-case creation uses the configured primary publication path before success
is confirmed. If it errors or times out:

1. do not assume another case is needed;
2. refresh the queue;
3. use Find; and
4. retry the retained submission only after checking current state.

### Later updates

For stages, remarks, and corrections, Django saves the canonical change first
and reserves durable background work for Sheet publication and notifications.

- **Saved** means the workflow action succeeded.
- **Publication queued for retry** means the case is saved and projection is
  pending.
- **Publication needs administrator attention** means the case is saved, but
  IT must inspect the background operation.

Do not repeat a saved stage to repair the Sheet.

### Optional support tabs

Some deployments also publish **CASE_INDEX** (reference/register lookup) and
**AUDIT LOG** (selected event information). They are secondary and may be
disabled. Their absence does not remove the Django case.

### Manual Sheet screenshots

> **Screenshot 20 — TAT Register overview**
>
> Add `docs/images/tat/20-tat-register-overview.png` here.
>
> **Screenshot 21 — One synchronized case row**
>
> Add `docs/images/tat/21-tat-synchronized-case-row.png` here.
>
> **Screenshot 22 — CASE_INDEX, if enabled**
>
> Add `docs/images/tat/22-case-index.png` here.
>
> **Screenshot 23 — AUDIT LOG, if enabled**
>
> Add `docs/images/tat/23-audit-log.png` here.

Build these examples with synthetic data. Blurring or cropping a live register
is not sufficient for a committed repository image.

### Business benefit

Synchronization supports register-based operations without making the Sheet a
second database or allowing cells to bypass stage rules.

---

## 17. Telegram batch intake

Batch intake is adjacent to, not a screen inside, the Mini App. An authorized
BRO or IT user can attach `.xlsx` or CSV in the configured group and send:

```text
@your_bot /batch
```

Required headers are **Product, Client Name, National ID, Phone, Branch,** and
**Amount**. The uploader needs batch capability and compatible branch/product
scope. Rows use the same validation principles as individual creation.

Use batch intake only for new loans. Correct existing cases in their detail
screen.

### Business benefit

Batch intake reduces repetitive entry while preserving server-side validation
and governed creation.

---

## 18. Good working practices

- Use the case reference in internal support; avoid customer identifiers.
- Start daily work with **Ready for my role**.
- Refresh after a long pause or old task link.
- Stamp only when the named business event happened.
- Write remarks that explain the obstacle and next follow-up.
- Correct an existing case instead of creating a duplicate.
- Treat Pilot records as test data.
- Protect downloaded workbooks according to JBL policy.

---

## 19. Errors and troubleshooting

### First response

1. Read the complete message.
2. Note reference, screen, action, and local time.
3. Keep a form open if it contains unsaved work.
4. Refresh only when asked for current state or safe to reload.
5. Never create another case or repeat a completed stage to bypass an error.

### Opening and access

| Problem | What it means / remedy |
|---|---|
| Unauthorized | Reopen from the approved bot. If it continues, ask the administrator to check the active TAT access grant and scope. |
| Expired/invalid link | Request a fresh `/tat` launch button. |
| Opens in ordinary browser | Return to Telegram and use the bot's Mini App button. |
| Wrong role/branch | Ask the administrator to correct access; never use another account. |
| Missing tab/button | Confirm role, scope, stage, and case state before escalating. |

### Queue and search

| Problem | Remedy |
|---|---|
| Ready queue empty | Remove filters, refresh, and inspect All cases if available. |
| Expected case absent | Search exact reference and have the administrator verify group/branch/product scope. |
| Refresh fails but old cards remain | The last confirmed queue was retained. Restore connectivity and retry. |
| Counts lag after a change | Wait briefly, refresh, and open the case for authoritative state. |

### Creation

| Problem | Remedy |
|---|---|
| ID rejected | Enter the National ID / Maisha Namba as issued: digits only, 1–9 digits. Do not enter the card serial number. |
| Phone rejected | Correct it to a valid Kenyan phone number. |
| Product/branch unavailable | Choose an in-scope active option or ask the administrator to correct access/availability. |
| Amount rejected | Use a valid whole-KES amount within the displayed product range. |
| BRO invalid | Select an available BRO; non-BRO creators must assign one explicitly. |
| Product evidence required | Complete every displayed required product field. |
| Existing loan found | Inspect it for correction; continue only for a separate loan. |
| Timeout/uncertain result | Refresh and Find before retrying the retained submission. |
| Outdated client | Close and reopen from Telegram, then review before submitting. |

### Stages and corrections

| Problem | Remedy |
|---|---|
| Stage locked | Read its reason; complete/route the real prerequisite. |
| Task already completed | Review refreshed state; do not force the old action. |
| Revision conflict | Preserve notes, refresh, review, and resubmit only if still correct. |
| Final amount required | Enter the whole-KES amount actually applied. |
| Product requirement missing | Complete the displayed evidence/custom field. |
| Closed Pilot | Use a case in the active operational cycle. |
| Legacy configuration unresolved | Ask an administrator to reconcile it in TAT Control Center. Do not edit it. |
| Correction unavailable | Use an authorized BRO/Head of Rural/IT user for case details or IT for completed stages. |

### Saving and Sheets

| Problem | Remedy |
|---|---|
| Publication queued for retry | The update is saved. Do not repeat it; refresh later. |
| Publication needs attention | The update is saved. Give IT the reference and time; do not edit the Sheet. |
| Sheet row stale | Trust the Mini App and report the reference to IT. |
| CASE_INDEX/AUDIT LOG absent | They may be disabled; use the Mini App. |
| Suspected duplicate Sheet row | Do not delete it. IT must use the governed inspection/repair process. |

### Private alerts

| Problem | Remedy |
|---|---|
| Cannot connect | Start/open the bot privately, return to Settings, and retry. |
| Bot blocked | Unblock, start privately, then reconnect. |
| Temporary failure | Work from Ready for my role and inform IT if persistent. |
| Link superseded | Open the current case from the queue. |
| No alert but case visible | Authorization and delivery are separate; confirm connection and continue from the queue. |

### Reports and downloads

| Problem | Remedy |
|---|---|
| TAT Reports missing | Ask whether Management/IT report access is appropriate. |
| Empty chart | Review date range and filters; follow any selection instruction. |
| Filter warning | Open filters; some active controls do not affect the focused insight. |
| Freshness warning | Refresh and ask IT if pending/failed rebuilds persist. |
| Stage progression requests one case | Narrow to an exact reference. |
| Copy unavailable | Retry in the active Mini App or use device selection if available. |
| More than 10,000 export rows | Narrow the report filters. |
| Download missing | Allow downloads, keep the app open, and check the Downloads folder. |

### Batch intake

| Problem | Remedy |
|---|---|
| `/batch` refused | Administrator must check batch capability and scope. |
| Headers rejected | Use Product, Client Name, National ID, Phone, Branch, Amount. |
| Row rejected | Correct the returned product/branch/identity/amount issue; do not duplicate accepted rows. |

### Escalating to IT

Provide the case reference, time, screen/action, exact message, whether the
action later appeared saved, affected scope, and app release from Settings.
Never include national ID, phone, documents, or a live-register screenshot in
ordinary support chat.

---

## 20. Quick reference

### Daily checklist

1. Open from the approved Telegram button.
2. Confirm account and data mode.
3. Start with Ready for my role.
4. Remove unintended filters.
5. Confirm the exact stage and real business event.
6. Record the action once.
7. Read the success/warning message.
8. Add useful delay context.
9. Refresh after a long pause.

### Key distinctions

- Ready for my role is an action queue; All cases is broader in-scope viewing.
- Requested amount starts the loan; final amount records what was applied and
  does not change the frozen path.
- Case-detail correction differs from IT-restricted completed-stage correction.
- A saved update with a Sheet warning remains saved; do not repeat it.
- Django/Mini App is workflow authority; Google Sheets is a projection.

---

## 21. Screenshot checklist

Capture ordinary small-phone viewports using only synthetic data.

| No. | Filename | Content |
|---:|---|---|
| 1 | `01-tracker-overview.png` | Header and Cases workspace |
| 2 | `02-telegram-launch.png` | Verified header after launch |
| 3 | `03-case-queues.png` | Ready and All queues |
| 4 | `04-queue-filters.png` | Filter sheet and pills |
| 5 | `05-create-case.png` | Complete synthetic form |
| 6 | `06-existing-loan-context.png` | Advisory prior-loan match |
| 7 | `07-find-case.png` | Find and safe result |
| 8 | `08-case-summary.png` | Summary, status, official TAT |
| 9 | `09-stage-states.png` | Complete/actionable/locked stages |
| 10 | `10-stage-outcome.png` | Outcome and final amount |
| 11 | `11-remarks-activity.png` | Remarks and Activity |
| 12 | `12-case-correction.png` | Audited correction panel |
| 13 | `13-settings-alerts.png` | Personal settings and alerts |
| 14 | `14-configuration-review.png` | Proposal/review |
| 15 | `15-pilot-mode.png` | Pilot/read-only state |
| 16 | `16-current-workload.png` | Workload metrics and insight |
| 17 | `17-report-filters.png` | Mobile report filters |
| 18 | `18-insights-table.png` | Insights and table controls |
| 19 | `19-period-performance.png` | Performance labels/metrics |
| 20 | `20-tat-register-overview.png` | Synthetic TAT Register |
| 21 | `21-tat-synchronized-case-row.png` | Synthetic synchronized row |
| 22 | `22-case-index.png` | Synthetic CASE_INDEX if enabled |
| 23 | `23-audit-log.png` | Synthetic AUDIT LOG if enabled |

Keep screenshots outside Git by default. If a fully synthetic image must be
committed, follow `docs/repository-data-artifact-policy.md`, including review,
metadata inspection, SHA-256 allowlisting, and explicit approval.
