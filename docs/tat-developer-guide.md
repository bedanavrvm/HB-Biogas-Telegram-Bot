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

Queue and legacy Find Case search share `_case_search_match`, but retain their
own capability intersection and group/branch/product/data-mode scopes. Matching
is applied before paging. ID/phone lookup retains the existing normalization
and exact-match rules; names, references, branches and BRO names use substring
matching. Do not introduce a search path that widens authorized visibility.

TAT opts into `installAccessibleForms(document, {alignFields: true})`. Existing
shared validation still owns errors, focus, aria associations and correction.
Compatible grid labels share caption, input and feedback row tracks; existing
help and inline errors stay in the same field feedback container. Dynamically
inserted fields adopt the pattern through the existing form observer. Checkbox
and mixed-content rows remain full width. Older WebViews without CSS subgrid
fall back to one column. Other Mini Apps do not opt in implicitly.

Report specialist controls remain inside the same form/API contract, under a
native More options disclosure. Keyboard focus excludes collapsed controls;
active non-applicable filters still raise a visible warning and reveal the
relevant disclosure when the user opens that warning. No reporting basis,
recognition formula, timer, stage gate or permission policy changes here.

The export POST accepts `prepare_download: true` for an opaque 15-minute link
and filename; legacy clients still receive XLSX bytes. GET/HEAD on
`/api/tat-tracker/reports/download/<token>/` rechecks the original active actor's
current group/capability and report scopes. Encrypted filter contents omit
Telegram credentials and keep search values out of URL logs; calendar dates
are frozen at preparation. The same audited exporter and 10,000-case cap apply.
Native Telegram acceptance is a handoff, never a completed-download receipt.

Both BRO selects use the organisation-wide active explicit TAT BRO roster.
Corrections submit user IDs; the server resolves the current display name and
retains selected identity in compliance metadata. Legacy name-only corrections
must uniquely match the active roster. A historical name can remain unchanged
when correcting another field. This does not change responsibility routing.

Task bootstrap/API pages default to ten personal assigned cases. The unread
badge never falls back to total assignments. Paging retains the current rows
on failure and exposes Retry. Refresh sequencing, dirty-form protection and
server-anchored timing remain intact; only the routine freshness label is hidden.

Sheet number formatting is best-effort, after value writes, for ordinary,
batch and repair publication. It must never change stored Decimal minutes or
turn a cosmetic provider failure into an unsuccessful canonical save.

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
