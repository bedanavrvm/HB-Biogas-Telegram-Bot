# ADR 0031: Database-leased operational jobs

**Status:** Accepted (31-August-2026)

## Context

Complaint export imports and TAT Sheet repairs previously started daemon
threads from webhook or Admin requests. An HTTP response could acknowledge
work whose only remaining state lived in one web process. A restart,
deployment, timeout, or multi-worker race could lose that work or execute it
concurrently.

The deployment does not have approved Redis/Celery infrastructure. PostgreSQL
is already the durable workflow source of truth and the platform has an
approved scheduler for bounded management commands.

## Decision

- HTTP and Admin requests reserve immutable work in Django and return without
  starting a thread.
- Complaint batches retain normalized item snapshots, hashes, status,
  attempts, outcomes, and a batch lease. TAT jobs retain their existing case
  list and cursor with the same database-lease model.
- Scheduled management commands claim jobs with row locks, process configured
  chunks, checkpoint every item/case, release the lease, and exit.
- Stale leases are reclaimable. Stable source message/case identifiers and
  existing domain uniqueness remain the replay boundary after a termination
  between an external call and its local checkpoint.
- Complaint completion Telegram delivery is a deduplicated durable integration
  operation. Runner and job health exposes aggregate, privacy-safe evidence.
- Shadow mode starts at one item/case per invocation. Required-runner
  production checks are enabled only after the scheduled commands have
  produced fresh heartbeats.

This supersedes ADR 0009 only where that earlier release said no scheduler was
enabled. Its bounded retry, circuit, and operator-visible integration rules
remain in force.

## Consequences

Acknowledged work survives web-worker replacement and deployments without new
queue infrastructure. Scheduled latency replaces immediate in-process work,
and operations must monitor two additional commands. PostgreSQL row locking is
the concurrency authority; SQLite tests verify semantics but production
overlap acceptance must use PostgreSQL.

## Alternatives considered

- **Keep daemon threads:** rejected because acknowledgement outlives neither
  the process nor its memory.
- **Celery and Redis:** rejected for this phase because it adds an unapproved
  broker, worker service, monitoring, and recovery surface.
- **Process everything in HTTP:** rejected because large imports and paced
  Google writes can exceed request and deployment time limits.
- **One unbounded scheduled run:** rejected because quota pacing and platform
  runtime limits need explicit work budgets.

## Rollback

Suspend both new scheduled commands before rolling application code back.
Preserve batch, item, repair, heartbeat, integration-operation, and audit rows.
Migration `core.0150_durablejobrunnerheartbeat_and_more` must not be reversed
after production jobs have been acknowledged without an approved evidence
export and forward recovery plan.
