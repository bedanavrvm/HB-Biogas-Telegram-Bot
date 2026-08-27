# TAT Mini App Developer Guide

## Architecture and authority

`core/services/tat_tracker.py` owns products, stages, server-side transitions,
revision checks, and Sheet publication. `tat_responsibilities.py` validates who
should receive work, while `tat_notifications.py` owns durable tasks, personal
inboxes, hash-only deep links, retries, backup escalation, and privacy-safe
group exceptions.

Telegram `initData` authenticates identity. `AccessGrant` authorizes workflow,
role, group, branch, and product scope. `TatResponsibilityAssignment` routes a
task but cannot grant access. Django cases and append-oriented events remain
canonical when Google publication fails.

## Write and notification contracts

- All Mini App writes require server validation and a stable retry key.
- Updates bind to the expected workflow revision and data-mode version.
- Money uses `Decimal`; timestamps are aware and displayed in Nairobi time.
- One case/stage/revision creates one action task. One task/user creates one
  recipient row. Delivery claims that row before crossing Telegram's boundary.
- Raw deep-link locators are never stored; only SHA-256 hashes are retained.
- The scheduled processor has a database-backed lease and append-oriented,
  aggregate health records. It must never include client or case data.
- Production readiness is delivery-mode aware: group mode does not require
  unused private rosters, shadow validates would-be routing without Telegram
  connections, and hybrid/private delivery requires both routing and connected
  primary recipients.

## Safe extension and validation

Add business rules to services, not templates or client JavaScript. Add an
allowed and denied/failure test to `docs/business_rule_test_map.md`. Run focused
TAT suites first, then the complete Django suite, Django checks, migration drift,
JavaScript syntax, and the mobile visual audit. Use staging Telegram and copied
Sheets for external verification; local automated tests must not contact real
services.

Operational deployment, scheduler behavior, readiness checks, monitoring, and
rollback are defined in `tat-production-runbook.md`. Calculation semantics are
defined in `../TAT_TRACKER_TAT_LOGIC.md`; access/routing details are in
`tat-access-and-responsibilities.md`.
