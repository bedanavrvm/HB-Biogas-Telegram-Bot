# Selected Origination deletion: 502 investigation and resource correction

The reported action was deleting Loan Origination applications in Django Admin.
The supplied 27 October 2026 excerpt shows a service restart around 10:10 Nairobi
time, but contains neither the failed deletion response nor an OOM/worker-timeout
reason. A restart alone does not prove why the gateway returned 502. Production
infrastructure and live records were not accessed or modified during this work.

Local synthetic tests reproduced two scaling faults in the actual selected-delete
service: the confirmation retained every stored PDF in its graph, and relationship
queries and mutation statements repeated for each individual record. A third
reproduction showed an HTTP retry returning 403 after successful deletion because
the Admin action compared its token against records that no longer existed.

The correction is in `core/services/miniapp_deletion.py` and
`core/admin_deletion.py`; regressions are in `core/tests_deletion_resources.py`.
The existing allowlist, signed impact, active-Superuser gate, full-row fingerprint,
transaction, locks, audit ledger, tombstones and provider isolation remain in force.
Shared products/documents and an application outside the selection survive.
Actual PDF changes still invalidate confirmation. Concurrent identical requests
retain one deletion and one replay. See ADR 0044 for the complete ownership policy.

| Scenario | Original local SQLite | Corrected SQLite | Corrected PostgreSQL |
| --- | --- | --- | --- |
| Preview 12 applications with 24 MiB stored PDFs | 24.38 MiB peak traced allocation | 1.13 MiB | 0.19 MiB |
| Preview 32 applications and 32 packages | 449 queries | 78 queries | 14 queries |
| Confirm 32 applications and 32 packages after the preview-only correction | 495 queries before mutation batching | 179 queries | 50 queries |
| Actual Admin preview/delete: 96 applications, 192 MiB PDFs | Not repeated with the unsafe original implementation | 3.56 MiB peak traced allocation, 5.29 seconds | 4.07 MiB, 5.42 seconds |
| Repeat the same completed Admin confirmation | 403 | Saved success response | Saved success response |

These are incremental Python allocations measured with `tracemalloc`, not total
worker RSS or Render capacity measurements. Stored synthetic PDF bytes exercise
deletion as opaque data; no PDF parsing or signing is performed by this action.
PostgreSQL evaluates `sha256(bytea)` on the stored binary values, so whole PDFs do
not cross the database connection for this operation. SQLite hashes one value at
a time. The fingerprint-equivalence regression verifies both paths against the
original full-row fingerprint.

Validation uses the isolated local database, ignores `.env`, and blocks remote
network connections. Reproduce with:

```powershell
.venv/Scripts/python.exe scripts/test_origination_configuration.py --postgres core.tests_deletion_resources core.tests_miniapp_deletion core.tests_origination_god_mode core.tests_product_permanent_deletion core.tests_group_reset
```

Omit `--postgres` for SQLite. PostgreSQL uses the dedicated test instance on port
55439. Logs are retained locally as `test-results/deletion-resources-*.log`;
the helper also writes machine-readable summaries under
`test-results/portal-local-audit-2026-10-26/`. Tests cover resource bounds, actual
Admin confirmation and response retry, selection tampering, changed PDF bytes,
oversized graph refusal, rollback, other-workflow retention, Sheet cleanup and
PostgreSQL concurrent confirmations.

Final results: 84 PostgreSQL tests passed with no skips; the same 84-test SQLite
run passed 82 and skipped the two PostgreSQL concurrency checks. Django detected
no new migrations, and `git diff --check` passed. This is focused deletion/reset
boundary coverage, not execution of the entire repository suite.

Deploy the corrected application code. This change needs no new migration,
setting or dependency and does not alter Gunicorn timeout/worker configuration.
It does not change the separate Origination full-reset or per-record God-mode
purge implementations. No production deletion or reset was run.

After deployment, correlate `Testing deletion requested`, `Testing deletion
preview ready` and `Testing deletion completed` logs. Completion includes the
stable request reference, counts, replay status and duration. Logs omit customer
fields, stored documents and confirmation tokens. If a 502 recurs, retain the
Render restart reason/memory event and these timing entries from the same period;
that distinguishes process termination from a long database wait. Production
cause and post-deployment success still require that operational evidence.

Code rollback is schema compatible but restores the resource problems. Deleted
records are recoverable only from a verified backup, as before this correction.
