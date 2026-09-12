# ADR 0032: Portal pipeline-stage UI and shared Mini App components

## Context

The Portal has grown into a collection of operational workspaces with sixteen
top-level destinations.  The individual workflows remain capability-scoped,
but their navigation, filters, pagination, feedback, and mobile data views do
not present one predictable interaction model.  TAT Tracker and Complaint
Cases already demonstrate the approved compact mobile patterns.

Changing Portal authorization or workflow transitions is outside this UI
work.  Existing browser routes and Telegram deep links must remain valid.

## Decision

Portal navigation is organized around the canonical operational pipeline:
Intake, Field Visit, Credit, Approval, Fulfilment, and Finance.  The persistent
mobile shell exposes four stable hubs: Home, Pipeline, Cases, and More.  The
server continues to omit destinations that the current actor cannot access.

Workflow-neutral presentation and interaction primitives live in a shared
Mini App component stylesheet and JavaScript module.  Portal adopts them
first.  TAT Tracker and Complaint Cases remain unchanged reference
implementations during this rollout.

Existing screen keys, route names, API endpoints, capability checks, state
transitions, audit behavior, and idempotency contracts are preserved.  The UI
stores only non-sensitive navigation preferences; customer searches and form
values are never persisted as UI context.

## Consequences

- Staff see work in loan-cycle order without learning the Portal's internal
  module boundaries.
- Deep links remain compatible while their active hub and stage are derived
  from server-owned navigation metadata.
- Shared components reduce per-workflow CSS and JavaScript drift.
- The Portal can migrate one surface at a time without changing operational
  records or requiring a schema migration.
- Compact density remains the default, with explicit minimum text and touch
  sizes for field use.

## Alternatives considered

- Keep all current top-level destinations and apply visual polish only.  This
  would retain the main navigation and discoverability problem.
- Put all six pipeline stages directly in the bottom bar.  This would exceed
  the approved four-item mobile navigation limit and produce unstable labels
  on narrow devices.
- Redesign TAT Tracker and Complaint Cases in the same release.  This would
  increase regression risk in already approved workflows without being
  necessary for Portal adoption.
