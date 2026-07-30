# ADR 0010: Per-Mini-App settings and governed TAT configuration

**Status:** Accepted for the pending 30-July-2026 release

## Context

Portal, Complaint Cases, TAT, and SPIN serve different operational workflows.
Staff need small personal choices—such as a landing screen, saved queue
filters, compact cards, and non-critical alert preference—without creating a
second access-control system or exposing structural controls casually.

TAT target values, the business calendar, and escalation routing have a wider
operational effect. A direct edit could change overdue interpretation or staff
notifications for an entire group. Existing cases must retain the target that
applied when they entered a stage, and past calendar data must remain available
to explain historical SLA calculations.

## Decision

- Settings are owned by each Mini App, not a single cross-workflow settings
  surface. Portal, Complaint Cases, TAT, and SPIN each store a single,
  user-owned `UserMiniAppPreference` record.
- Personal settings are available only to the authenticated user and contain
  validated defaults/filters, compact-card mode, and an intent for
  non-critical notifications. Mandatory security, assignment, approval, and
  overdue-breach alerts are never suppressible through this preference.
- TAT exposes operational configuration only through code-defined capabilities:
  IT may propose target, future-calendar, and escalation-rule changes; a
  different authorised Admin must approve or reject each proposal.
- TAT configuration proposals preserve before/proposed snapshots, requester,
  reviewer, reason, and application timestamps. Approval writes an append-only
  compliance event.
- Approved TAT target changes apply only to future stage entries. Each active
  case carries a stage-target snapshot and historical target values are never
  recalculated from a later setting.
- The Mini App may edit only future business-calendar holidays. Historic
  holiday records remain immutable evidence. Business hours remain fixed at
  Monday–Friday, 08:00–17:00, Africa/Nairobi in this release.
- The current shared Telegram-group alerts are unchanged. Personal
  immediate/daily-digest/quiet choices are persisted as preferences only until
  an approved recipient-level delivery ledger and digest scheduler exist.

## Consequences

Staff receive a compact, workflow-relevant settings experience without
gaining configuration rights through UI visibility. TAT configuration changes
are reviewable and attributable, and in-flight SLA results remain explainable.

The design adds controlled local models and migrations but starts no scheduler,
does not send Telegram/SMS alerts, and does not write to Google Sheets or
Drive. A future notification-delivery implementation must honour only
non-critical preferences and retain a delivery audit trail.

## Alternatives considered

- **One global settings page:** rejected because it would mix unrelated
  workflow contexts and make capability/scoping decisions harder to explain.
- **Direct editable TAT settings:** rejected because a single user could change
  operational SLAs or escalation routing without independent review.
- **Live recomputation of every target after a change:** rejected because it
  rewrites the explanation of already-running stages.
- **A new generic permission system for settings:** rejected because existing
  workflow capabilities already provide the server-side enforcement point.

## Rollback

This ADR is implemented by
`core.0085_tattrackercase_stage_target_snapshots_and_more`,
`core.0086_seed_tat_target_snapshots`, and
`core.0087_repair_tat_stage_target_snapshot_backfill`. Neither migration is
authorised for production application by this ADR.

Before rollback, export approved `WorkflowConfigurationChangeRequest` records
and retain their compliance-audit evidence. To undo the schema after an
approved release, run:

```powershell
python manage.py migrate core 0084_integrationcircuitstate_integrationoperation
```

Roll back the related code in the same change. Do not delete historical
configuration-request or compliance evidence as part of rollback.
