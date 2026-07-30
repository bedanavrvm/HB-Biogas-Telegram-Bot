# ADR 0009: Bounded, operator-visible integration reliability

**Status:** Accepted for the pending reliability release (30-July-2026)

## Context

Portal, Complaint Cases, TAT, and SPIN write canonical state in Django and
then synchronize selected records, documents, or notifications through Google
Sheets, Google Drive, and Telegram. Mobile WebViews and Telegram can retry a
request. External APIs can also fail transiently or be rate limited.

This Render deployment has no approved Celery/Redis worker or scheduler. A
process-local retry thread would be lost on restart and would conceal a failed
financial or workflow side effect from the staff member who initiated it.

## Decision

- Mini App writes accept `Idempotency-Key`, `X-Request-ID`, and existing body
  request identifiers. Refreshed clients submit one key per user action and
  reuse it on a retry. Older clients remain accepted while
  `REQUIRE_MINIAPP_IDEMPOTENCY_KEY=False`, with an explicit response warning.
- `IntegrationOperation` stores a redacted, deduplicated external-operation
  register; `IntegrationCircuitState` stores bounded circuit health. Neither
  stores documents, tokens, raw Google errors, or customer payloads.
- Google Sheets retries at most four times; Google Drive and Telegram at most
  three. Only network/timeouts, 429/rate-limit and 5xx failures retry. A
  circuit opens after five transient failures in five minutes, cools down for
  ten minutes, then permits one recovery probe.
- The migrated shared transport paths record a durable operation before an
  outbound call. Where the owning workflow has already committed canonical
  state, an external failure is retryable/dead-lettered and must not be
  returned as a successful synchronization. Legacy call-order refactors remain
  separately tracked rather than being silently claimed complete.
- `probe_integrations` is manual. Without `--execute` it only checks local
  configuration; the explicit flag makes read-only metadata calls. No
  scheduler or live probe is enabled by this release.
- `/api/readiness/` is protected by `API_AUTH_TOKEN` and reports stored DB,
  migration, circuit and operation state only. `/api/health/` remains the
  public DB liveness endpoint.

## Consequences

Staff receive a truthful save/sync outcome and admins can see why a sync needs
attention. The design is intentionally not eventual background delivery: a
dead-lettered operation must be reviewed and retried from the owning workflow.

Existing direct external callers are not all refactored in this bounded
release. New shared Sheets batch writes, Drive uploads, and Telegram launcher
publishing use the register; remaining paths are tracked in `TECH_DEBT.md`.

## Alternatives considered

- **Celery + Redis:** rejected for this release because it introduces new
  production infrastructure, monitoring, backup and recovery requirements.
- **Infinite in-request retry:** rejected because it can exhaust quotas and
  leaves users waiting without an actionable record.
- **Process-local background thread:** rejected because a Render restart loses
  work and violates the durable-operation requirement.

## Rollback

This ADR's schema is migration `core.0084_integrationcircuitstate_integrationoperation`.
It has not been applied to production. After exporting any required operation
evidence, the schema rollback is:

```powershell
python manage.py migrate core 0083_complianceauditchainstate_complianceauditcheckpoint_and_more
```

Code rollback must occur together with the schema rollback. Do not remove a
successful local document/Sheet result while rolling back the operations
register.
