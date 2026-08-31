# Durable Complaint Import and TAT Repair Runners

Complaint imports and TAT Sheet repairs are database-backed jobs. HTTP and
Django Admin requests only validate and reserve work; they never start a
process-local thread. This keeps acknowledged work recoverable across web
worker restarts and deployments without Celery or Redis.

## Scheduled commands

Provision both commands in the approved scheduler, normally once per minute:

```text
python manage.py process_complaint_imports --max-batches 1
python manage.py process_tat_repairs --max-jobs 1
```

Each invocation claims work with a row lock and lease, processes a bounded
chunk, checkpoints each item or case, and exits. Overlapping schedulers cannot
claim a live lease. A later invocation reclaims a lease after
`DURABLE_JOB_LEASE_SECONDS`.

The complaint runner also attempts due completion-notification operations.
Those Telegram calls use the durable integration-operation register and its
bounded retry policy. No uploaded export file is retained after the webhook
acknowledgement; the transaction stores the normalized entry snapshots needed
for audit and replay.

## Controlled rollout

1. Deploy the migration with `COMPLAINT_IMPORT_RUNNER_REQUIRED=False`,
   `TAT_REPAIR_RUNNER_REQUIRED=False`, and
   `DURABLE_JOB_RUNNERS_SHADOW_MODE=True`.
2. Provision both scheduled commands. Shadow mode still executes work, but
   hard-limits each command to one item or case so lease recovery and external
   behavior can be observed at low volume.
3. Confirm fresh `Durable job runner heartbeat` rows, no unexplained stalled
   jobs, and correct outcomes using synthetic/staging data.
4. Increase the configured chunk limits deliberately and set
   `DURABLE_JOB_RUNNERS_SHADOW_MODE=False`.
5. Set both `*_RUNNER_REQUIRED=True`. Production readiness then fails when a
   required runner has not reported within
   `DURABLE_JOB_RUNNER_MAX_SILENCE_SECONDS`.

The public health response and protected readiness response expose only
aggregate counts, freshness, and privacy-safe error codes. They do not include
entry snapshots, case identifiers, request bodies, or customer data.

## Operator controls

- Complaint batches: Django Admin → Complaint case import batches. An active
  Superuser can retry failed/cancelled items or cancel outstanding work.
- TAT repairs: use the TAT reconciliation page. Creating or retrying a repair
  queues it; cancellation retains completed case checkpoints.
- A `partial` complaint batch is terminal until explicitly retried. Successful,
  matched, and skipped items are not reset.
- A `completed_with_errors` TAT job lists the failed case IDs. Retry creates a
  new job containing only those failed IDs.

Do not edit job cursors, lease tokens, snapshots, or outcome references in the
database. Do not re-create canonical workflow records to compensate for an
external failure.

## Monitoring and incident handling

Alert on non-zero command exits, stale required-runner readiness errors, and
stalled-job warnings. A single stale lease is recoverable; repeated stale
leases indicate scheduler overlap, a runtime limit, or an external dependency
that needs investigation.

To halt processing, suspend the relevant scheduled command and cancel queued
jobs through its approved operator surface. Preserve job, item, integration,
and audit rows. Resume with the same database after correcting the cause; do
not purge or rewind checkpoints.
