# TAT Tracker Calculation, Status, and Highlighting Logic

This document explains how the TAT Tracker calculates turnaround time, how case status changes, and how the sheet/mini app should interpret the values.

> **Current implementation note (July 2026):** The sections below describe the business rules. The definitive implementation is Django-calculated TAT values, IT-managed minute targets, and sheet-local helper cells for conditional formatting. The `TAT TARGETS` support tab is created automatically on the first successful IT target save; it is not expected to exist before that action.

## Current Target and Highlighting Implementation

### Data ownership and flow

Django owns workflow timestamps, calculations, targets, and SLA classification. The Google workbook is the operational display; Apps Script only sets up workbook formatting and conditional rules.

```text
Telegram Mini App stage update
  -> Django stores case state and append-only audit event
  -> Django calculates total and per-stage elapsed values
  -> Django writes numeric display values to the tracker tab

IT saves Targets in the Mini App
  -> Django stores tat_targets_minutes in the group workflow
  -> Django creates/synchronizes the TAT TARGETS support tab
  -> Apps Script copies target lookups into hidden same-sheet helper cells
  -> Google Sheets conditional formatting colours visible TAT cells
```

Saving source files in this repository does **not** update the live Google Apps Script. The latest `tat_tracker_apps_script.gs` must be pasted/saved in the workbook’s Apps Script project.

### Canonical unit: minutes

All targets are whole **minutes**. Hours and days are display conversions only.

| Value | Unit | Calculation |
|---|---:|---|
| Overall TAT | minutes | `end - created` |
| TAT Hours | hours | `overall minutes / 60` |
| TAT Days | days | `overall minutes / 1440` |
| Stage TAT / lag | minutes | `stage end - previous completed stage` |

The hour and day values are rounded to two decimal places. Target inputs must be whole minutes between `0` and `5,256,000`.

### Overall TAT end point

The start is always the case creation timestamp. The end is selected by state:

| Status | Overall TAT end |
|---|---|
| `Rejected` / `Declined` | Decision timestamp |
| `Disbursed` | Finance disbursement timestamp |
| Any non-terminal status | Current Kenya time, so the value continues running |

Negative differences are clamped to zero. Timestamps are timezone-aware and displayed in `Africa/Nairobi`.

### Stage lag calculation

The first stage starts at case creation. Every later stage starts when the immediately preceding completed stage ended. The current next actionable stage is live-calculated to the present time; later unreachable stages remain blank.

```text
MPESA sent to Admin lag = MPESA sent timestamp - case created timestamp
MPESA verified lag      = MPESA verified timestamp - MPESA sent timestamp
```

Dropdown stages use their automatic timestamps for the calculation where available:

- Decision → `decision_ts`
- Sanctions → `sanctions_ts`
- Disbursement register → `register_ts`

### Target storage and lookup

IT staff configure targets in the Mini App. Django stores them under `tat_targets_minutes` by product and stage key:

```json
{
  "tat_targets_minutes": {
    "sme": {
      "total": 20160,
      "stages": {
        "mpesa_to_admin": 60,
        "mpesa_verified": 120
      }
    }
  }
}
```

On save, the same values are written to `TAT TARGETS`:

| Column | Contents |
|---|---|
| A | Product key: `sme`, `logbook`, `mjengo`, `kilimo`, or `micro_asset` |
| B | `__total__` or the exact stage key |
| C | Target minutes |
| D | Near ratio (`0.8`) |

The total target defaults to `20,160` minutes (336 hours / 14 days) per product. Stage targets are optional and blank by default. Without a positive target, the elapsed value remains visible but correctly receives no SLA colour.

### Near ratio and traffic lights

The near ratio is `0.8`, meaning 80% of the target.

```text
near threshold = target × 0.8
```

| Elapsed value | SLA state | Sheet colour |
|---|---|---|
| Blank, or no positive target | blank | No colour |
| Less than 80% of target | `within` | Green |
| At least 80% and at most 100% | `near` | Amber |
| More than 100% | `over` | Red |

Boundary examples for a 60-minute target:

| Elapsed | Result |
|---:|---|
| 47 minutes | Green |
| 48 minutes (80%) | Amber |
| 60 minutes (100%) | Amber |
| 61 minutes | Red |

For the overall totals, Apps Script converts the minute target before comparison:

- `TAT Hours` compares against `target minutes / 60`.
- `TAT Days` compares against `target minutes / 1440`.
- Stage-lag columns compare directly in minutes.

### Why the support tab and helper cells matter

Google conditional formatting cannot reliably evaluate a formula that directly reads a different tab. The script therefore reads `TAT TARGETS` into hidden cells on each tracker tab and has the visible conditional rules reference only those same-sheet cells. This prevents the “conditional format rule cannot reference a different sheet” failure.

### Required setup and recovery checklist

1. Deploy Django so the automatic `TAT TARGETS` creation code is live.
2. Confirm the Google service account is an Editor on the tracker workbook.
3. As an IT user, save the total and stage targets once in the Mini App.
4. Confirm `TAT TARGETS` now exists and contains rows such as `sme | __total__ | 20160 | 0.8`.
5. Update and save `tat_tracker_apps_script.gs` in **Extensions → Apps Script**.
6. Reload the workbook and run **TAT Tracker → Refresh TAT highlighting**.
7. Test a value below 80%, at 80–100%, and above 100%.

If the cell still has no colour after these steps, verify the product key and stage key exactly match the rows in `TAT TARGETS`; a missing or zero target intentionally produces no colour.

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

- `case_id`, for example `JBL-BS-2026-001`
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

On save, Django synchronizes the targets to the `TAT TARGETS` support tab. Apps Script mirrors those values into hidden helper cells on each tracker tab, and the visible conditional-format rules read only those local cells. This keeps the Mini App badges and sheet traffic lights aligned without treating Google Sheets as the workflow source of truth.
