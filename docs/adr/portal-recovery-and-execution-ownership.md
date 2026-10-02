# Portal recovery and execution ownership

## Context

The October 2026 engineering audit reproduced stale claims, late completions,
global publication coupling and interrupted invoice replay. The user authorized
remediation excluding EQ-06 and EQ-11. Canonical saves must not wait for Sheets,
and cron/Redis/Celery remain outside scope.

## Decision

Use the existing IntegrationOperation register with a unique attempt token in
durable metadata. Validate eligibility under its row lock and fence completion
against that token. Retain terminal evidence and reviewed replacement retries.
Bind publication FIFO to destination identity while retaining shared pacing.
Use existing invoice batch metadata to checkpoint ingestion; interrupted uploads
without a known external outcome require reconciliation rather than blind resend.
Keep processing request-assisted and bounded, with no process-local background
thread. Reuse existing models; no schema change is required for these contracts.

## Consequences

This prevents obsolete workers from rewriting current outcomes, but does not
promise exactly-once remote side effects. Old unfenced workers must be drained
before enabling the new executor. Unattended progress and production repair need
separate operational authorization. EQ-06 logging and EQ-11 broad cleanup remain
unchanged; only narrow service extraction needed by the CI gate is in scope.

## Alternatives considered

Redis/Celery or cron: rejected by scope. Holding database locks during Google
calls: rejected for capacity/deadlocks. Resetting failed attempts in place:
rejected because it discards operational history. Blind Drive resend after a
timeout: rejected because remote acceptance is uncertain.
