# TAT Tracker Calculation, Status, and Highlighting Logic

This document explains how the TAT Tracker calculates turnaround time, how case status changes, and how the sheet/mini app should interpret the values.

## Source Of Truth

Django is the source of truth for TAT cases.

The Google Sheet is the operational/reporting surface. Django writes case data and calculated TAT values into the sheet when a case is created or updated. The Apps Script is used for sheet setup, validations, formatting, and conditional highlighting.

Key implementation files:

- `core/services/tat_tracker.py` - case creation, stage updates, status changes, TAT calculations, and Google Sheet sync.
- `tat_tracker_apps_script.gs` - sheet setup, dropdowns, formats, and conditional highlighting.
- `TAT_TRACKER_MINI_APP_GUIDE.md` - deployment and usage guide.

## Case Lifecycle

A case starts when staff create it in the TAT Tracker Mini App.

At creation, Django stores:

- `case_id`, for example `JBL-SME-2026-001`
- product type, for example `sme`, `logbook`, `mjengo`, `kilimo`, or `micro_asset`
- client name
- national ID number
- primary phone number
- branch
- BRO name
- amount
- `stage_values.created`, the timestamp used as the total TAT start time
- status = `Active`
- current stage = the first workflow stage for that product

Each later stage update is stored in `stage_values` and also creates a `TatTrackerEvent` audit row.

## Product Workflows

The workflow differs by product.

### SME

SME stages are:

1. MPESA sent to Admin
2. MPESA verified and sent to CA
3. Credit analysis sent
4. BRO response to CA
5. BM response to CA
6. BRO applied loan on system
7. Disbursement register
8. Register approved
9. Finance disbursement

### Logbook

Logbook stages are:

1. MPESA sent to Admin
2. MPESA verified and sent to CA
3. Credit analysis sent
4. BRO response to CA
5. Valuation ready
6. BM TAT request sent
7. HOCC scheduled
8. HOCC held
9. Decision
10. Minutes shared
11. Sanctions
12. BRO applied on system
13. Disbursement register
14. Register approved
15. Finance disbursement

### Mjengo, Kilimo, and Micro Asset

These use the same non-valuation path:

1. MPESA sent to Admin
2. MPESA verified and sent to CA
3. Credit analysis sent
4. BRO response to CA
5. BM TAT request sent
6. HOCC scheduled
7. HOCC held
8. Decision
9. Minutes shared
10. Sanctions
11. BRO applied on system
12. Disbursement register
13. Register approved
14. Finance disbursement

## Total TAT Calculation

Total TAT starts at case creation:

```text
start = stage_values.created
```

The total TAT end point depends on case status:

- If status is `Rejected` or `Declined`, TAT ends at the decision timestamp if available.
- Otherwise, TAT ends at the finance disbursement timestamp if available.
- If the case has not reached its end point, TAT is calculated up to the current time.

Formula in business terms:

```text
total_tat_minutes = end_time - created_time
```

Django stores/displays derived values:

```text
tat_hours = total_tat_minutes / 60
tat_days = total_tat_minutes / 1440
```

The values are rounded to 2 decimal places.

## Default TAT Target

The default total target is:

```text
20160 minutes = 336 hours = 14 days
```

This default currently applies to:

- SME
- Logbook
- Mjengo
- Kilimo
- Micro Asset

The near-target threshold is 80% of the target:

```text
near threshold = target * 0.8
```

For the default 14-day target:

```text
near threshold = 268.8 hours = 11.2 days
```

## SLA Status Values

Django classifies TAT using `sla_status`:

| Status | Meaning |
|---|---|
| blank | No TAT value or no target configured |
| `within` | TAT is below 80% of target |
| `near` | TAT is at or above 80% of target but not over target |
| `over` | TAT is greater than target |

Important detail:

```text
minutes > target  => over
minutes >= target * 0.8 => near
otherwise => within
```

So exactly equal to the target is still not `over`; it becomes `over` only after exceeding the target.

## Stage TAT Calculation

Stage TAT measures how long a stage took relative to the previous completed stage.

For each stage:

```text
stage_start = timestamp of previous completed stage
stage_end = timestamp of this stage
stage_tat_minutes = stage_end - stage_start
```

For the first stage, the previous timestamp is case creation.

Example for SME:

```text
Case Created -> MPESA sent to Admin
MPESA sent to Admin -> MPESA verified and sent to CA
MPESA verified and sent to CA -> Credit analysis sent
```

If the stage is the current pending stage, Django can calculate a live running stage TAT using current time:

```text
stage_tat_minutes = now - previous completed stage timestamp
```

If a later stage is not yet reachable because previous stages are incomplete, stage TAT is blank.

## Stage Targets

Stage targets are optional.

They are configured in the workflow JSON under `tat_targets_minutes`:

```json
{
  "tat_targets_minutes": {
    "sme": {
      "total": 20160,
      "stages": {
        "mpesa_to_admin": 60,
        "mpesa_verified": 120,
        "ca_analysis_sent": 1440
      }
    }
  }
}
```

Where:

- `total` is the overall case TAT target in minutes.
- each key under `stages` is a stage key.
- each stage value is that stage's target in minutes.

If a stage has no configured target, the mini app can show stage elapsed time but cannot classify that stage as within/near/over.

## Sheet Columns For TAT

The product tracker sheets have normal workflow columns and TAT summary columns.

Common TAT summary columns:

- `TAT Hours`
- `TAT Days`

Django writes numeric values into these columns during sync.

Some sheet formats can also include stage-specific TAT columns. Django supports these by header aliases such as:

- `<Stage Label> TAT Minutes`
- `<Stage Label> TAT`
- `<Stage Label> Lag`
- `<Stage Label> Lag Minutes`
- `<stage_key> TAT Minutes`

If those columns exist, Django writes numeric stage TAT minutes into them.

## Status Logic

Case status is not just a sheet dropdown. It is controlled by workflow stage updates.

### Active

New cases start as:

```text
Active
```

A case remains active while it is moving through normal stages.

### Deferred

When the `Decision` stage is set to `Deferred`, Django sets:

```text
status = Deferred
```

This means the case has gone through decision review but is not rejected or disbursed.

### Rejected

When the `Decision` stage is set to `Rejected`, Django sets:

```text
status = Rejected
```

For rejected cases, total TAT ends at the decision timestamp.

### Disbursed

When the `Finance disbursement` stage is completed, Django sets:

```text
status = Disbursed
```

For disbursed cases, total TAT ends at the disbursement timestamp.

### Declined

`Declined` is supported as a terminal status in the status list and queue filtering. It is treated like rejected for TAT end-time purposes, but current Mini App stage side effects set `Rejected` from the decision stage, not `Declined`.

### Stalled and Pending Docs

`Stalled` and `Pending Docs` are valid sheet status values for reporting/filtering, but current automatic Mini App side effects do not set them directly. They are available for operational use if the workflow is extended or staff/admins update the sheet/status manually.

## Queue Logic

The Mini App action queue excludes terminal statuses:

```text
Disbursed
Rejected
Declined
```

For active/non-terminal cases, the app finds the first incomplete stage. That is the next action.

A staff member sees a case in their action queue only if:

- the case is not terminal,
- the next incomplete stage exists,
- the staff member's role can update that stage,
- the staff member is allowed for the case branch,
- the staff member is allowed for the product.

## Stage Update Rules

The Mini App enforces sequence.

A user cannot update a later stage before previous stages are complete.

Examples:

- Admin cannot verify MPESA before BRO marks MPESA as sent.
- Finance cannot disburse before register approval is complete.
- BRO cannot apply on system if sanctions are required and sanctions are not marked `Met`.

For timestamp stages, the app stores the current timestamp.

For dropdown stages, the selected value is stored. Some dropdown stages also create an automatic timestamp:

- `Decision` creates `decision_ts`
- `Sanctions` creates `sanctions_ts`
- `Disbursement register` creates `register_ts`

## Sheet Highlighting

The Apps Script controls visual highlighting in Google Sheets.

Current setup includes conditional formatting for:

- `TAT Hours` and `TAT Days`
- status-driven row highlighting
- stage traffic-light highlighting, if configured in the script

For total TAT value cells:

| Condition | Highlight |
|---|---|
| TAT above 80% of target but not over target | Amber/yellow |
| TAT over target | Red |

For status rows:

| Status | Highlight |
|---|---|
| `Disbursed` | Green |
| `Rejected` | Red |
| `Declined` | Red |
| `Deferred` | Amber/yellow |
| `Stalled` | Orange |
| `Pending Docs` | Blue |

## Important Clarification About Stage Highlighting

Stage highlighting should be based on whether each stage met its own stage TAT target.

The correct business rule is:

| Stage result | Meaning | Color |
|---|---|---|
| stage completed within target | Met target | Green |
| stage elapsed is near target | At risk | Amber |
| stage completed over target or currently overdue | Missed target | Red |

This requires stage-level targets to be configured. Without stage targets, the sheet can show elapsed stage time, but it cannot honestly say whether that stage met or missed target.

If a sheet rule only checks whether a stage cell is blank or filled, that is not enough. A completed stage can still be late, and a pending stage can still be within target.

## Recommended Stage Target Setup

Define realistic targets per stage in minutes. Example only:

```json
{
  "tat_targets_minutes": {
    "sme": {
      "total": 20160,
      "stages": {
        "mpesa_to_admin": 60,
        "mpesa_verified": 120,
        "ca_analysis_sent": 1440,
        "bro_response": 1440,
        "bm_response": 1440,
        "bro_applied": 480,
        "disbursement_register": 240,
        "register_approved": 240,
        "disbursement": 480
      }
    }
  }
}
```

The exact values should come from JBL's agreed SLA/TAT policy, not from the code.

## How To Interpret A Case

When reviewing a case, read it in this order:

1. Check `Status`.
2. Check `TAT Hours` / `TAT Days` for total case age.
3. Check the next incomplete stage in the Mini App.
4. Check stage TAT columns, if available.
5. If a stage is red, identify whether it is currently pending past target or completed late.
6. Use `Remarks / Delays` for operational explanation.
7. Use `AUDIT LOG` to see who updated which stage and when.

## Reset And Manual Edits

The Django database stores the authoritative case state. The sheet can be sorted and filtered.

If a sheet row is deleted manually:

- the Django case still exists,
- the Mini App can still find it,
- on the next update, Django searches by `Case ID`,
- if missing, Django appends the case again.

Do not manually edit stage timestamps unless you are deliberately correcting a record. Manual edits can make TAT calculations inconsistent with the audit trail.

## Target Administration

Staff with the TAT `IT` role configure total and stage targets in the Mini App. Django stores them in the group workflow under `tat_targets_minutes`, using minutes as the canonical unit.

On save, Django synchronizes the targets to the Apps Script-owned `TAT TARGETS` support tab. Conditional-format formulas for total and stage lag columns read that tab directly. This keeps the Mini App badges and sheet traffic lights aligned without treating Google Sheets as the workflow source of truth.
