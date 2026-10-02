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

### Portal layout and inbox contract (2 October 2026)

Portal toolbars and panel headings use the shared `miniapp-toolbar` and
`miniapp-panel-heading` patterns, with `miniapp-icon-button` controls (44px
targets, 20px icons). Legacy broad header rules must exclude these patterns.
Consumers must not redefine their alignment or dimensions with screen IDs.
Portal adopts these patterns without changing other Mini Apps.

The bell represents distinct authorized actions, not sampled prompts or case
totals. Its read interface returns ten items per page and the total from the
same deduplicated action collection used by Home. A payment batch is one task;
each import worklist and failed integration operation is one task. No new
persistent inbox or permission grant is introduced.

Full-shell browser tests must use the production stylesheet order. They assert
right-edge alignment and touch sizes, capture reviewed visual baselines, and
exercise pagination and scoped totals. Fragment-only screenshots cannot approve
changes to shared Portal controls.

Run the controls contract with `npx playwright test
core/tests_browser/portal_recognition_layout.spec.js
core/tests_browser/portal_inbox.spec.js core/tests_browser/portal_consistency.spec.js`.
These tests compose the real shell/template assets in production CSS order with
synthetic API data; they are not a live Telegram or Google integration test.
The matrix includes 320, 360, 390, 430, 768 and 1280px and both themes.
Visual baselines live under `core/test_fixtures/sanitized/portal-layout/`;
review screenshots before using `--update-snapshots`, then update their exact
SHA-256 entries in `scripts/tracked_artifact_allowlist.json`. Never approve
CI-generated replacements blindly or put customer screenshots in this folder.
Geometry assertions remain mandatory even when baselines are deliberately updated.

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
