# Origination configuration isolation: implementation and validation

Implemented 26 October 2026. Deployment migration: `origination.0014`.

## Result

- Seed signer suggestions no longer block document use. An empty document signer
  list does not inherit Product signers. Static supporting PDFs can join a shared-value packet.
- Explicit identity mappings can use selected Main LAF/application values without
  recreating deleted document fields. The existing OTP and participant checks remain.
- Deleting signing placements updates the owning document's obligations and removes
  paired dates. Removed dates stay removed on later signer edits. Exact request retries
  return the retained revision even when the server removed a paired date.
- Placement policy v2 validates retained fields rather than an old seeded universal
  identity requirement. Signed snapshots and historical v1 contracts remain unchanged.
- Origination owns requirements/custom attributes on its existing Product definition.
  Global financial terms remain shared. Local successors preserve document fields and
  the financial version unless shared financial editing is explicitly selected.
- New catalogue applications retain visible amount/tenor inputs independently of PDF
  placement, with one entered value and existing Decimal-based financial validation.
- Origination reset preserves shared Products, terms, TAT state and availability.
  Global catalogue reset refuses other-app configuration, availability, access or history.
- Document copying now opens its own transaction; independent concurrent requests reuse one copy.

## Passing verification

| Check | Result | Local evidence |
|---|---|---|
| Final SQLite regression set | 156 passed, no skips | `test-results/origination-final-regressions-sqlite.log` |
| PostgreSQL concurrency/browser set | 95 passed, no skips; includes all 14 PostgreSQL-only cases from the SQLite sweep | `test-results/origination-final-regressions-postgres.log` |
| Final PostgreSQL document/retry regression set | 121 passed, no skips | `test-results/origination-idempotency-postgres.log` |
| Four real Chromium Admin workflows | Passed: authoring/publication, removal/shared identity/reload, attachment, shared edit/withdrawal | Logs above and `test-results/origination-configuration-browser/` |
| Migration/model state | No ungenerated migrations | `makemigrations --check --dry-run` in isolated settings |
| UI registry, JavaScript syntax and whitespace | Passed | `scripts/check_ui_standard.py`, `node --check`, `git diff --check` |

Broader sweeps exercised 725 SQLite and 318 PostgreSQL cases. Two older assertions
treated empty static PDFs as incompatible with shared-value documents; those tests
now use actual legacy input fields to retain their intended incompatibility check,
and pass in the final regression sets. The entire broad sweep was not repeated after
these fixture corrections or the final paired-date retry fix. The affected document,
editor, template and concurrency boundaries were rechecked above. Older migration
upgrade/reverse tests also ran in the broader SQLite sweep.

The dedicated tests cover shared values, finance inputs/quotes, requirement snapshots,
removal, retry, versioning, migration copying, reset rollback/protection and signed-history
compatibility. Retained test databases restore missing Origination built-in capability
fixtures before execution; production grants or settings are never changed by the harness.

## Reproduction and deployment

Use `.venv/Scripts/python.exe scripts/test_origination_configuration.py` followed by
the desired Django test labels. `--postgres` targets the dedicated synthetic loopback
cluster on port 55439. The helper ignores `.env`, uses local databases and allows only
loopback connections; provider/storage behavior is mocked in the relevant fixtures.
The temporary PostgreSQL instance was stopped after validation. No live Sheets, Drive,
SMS, Telegram, email, operational database or deployment migration was used.

Deploy migration 0014 with the code. It copies existing applicable configuration into
Origination definitions without deleting the shared rows or rewriting applications.
No reseeding or reset is required. Export local configuration before rolling back its
new column. Recovery of products affected by a previous reset is a separate audit task.

Real provider delivery, production data, physical Telegram devices and screen readers
were not tested. These checks do not certify production rollout or full design adoption.
