# Origination ownership and Mini App reference foundation

Loan Origination now belongs to the `origination` Django app in the existing
deployment and database. It owns its 27 models, services, HTTP boundary, admin
screens, templates and static assets. Shared products, locations, staff and
canonical customer identities remain in `core`.

Existing tables retain their physical `core_*` names. This is an explicit
adoption exception for the frozen 27-model migration manifest, not a naming
exception for new models. IDs, constraints, relationships, document bytes,
hashes and historical audit entries remain intact. Content-type IDs and their
permission assignments transfer to `origination`; permissions are not recreated.
The database catalogue records purpose, lifecycle, retention, column comments
and reasons for preserving each existing index.

## Access and configuration

Create fresh AccessGrants for workflow **Loan Origination** (`loan_origination`).
Existing Portal grants confer no Origination access and are never copied.
`origination.view`, `origination.create`, `origination.review`,
`origination.signing.start` and `origination.signing.staff` replace the former
Portal-owned capabilities. IT remains bounded by its grant scope; active Django
Superusers retain the explicit technical override.

Officers create and edit their own applications. Operations and Business
Administrators review; Operations starts signing. Officers, Branch Managers,
Management and Credit Analysts sign only their permitted configured staff roles.
Read and write authorization evaluates a complete branch/product/group grant
tuple, including current temporary grants. Independent group setup uses the
**Loan Origination** workflow preset. New applications retain that selected group;
historical applications remain ungrouped. A group-restricted grant cannot claim
historical ungrouped applications. Restarting a draft preserves its original group.

Keep `ORIGINATION_WEBAPP_REQUIRE_TELEGRAM_AUTH=True` in production and use a
positive `ORIGINATION_WEBAPP_AUTH_MAX_AGE_SECONDS` (default 86400). The independent
boundary delegates signature verification to the shared canonical Telegram
identity service. Product availability still uses workflow `loan_origination`
and the existing `portal` delivery channel; this channel is not Portal authority.

Existing `/origination/`, `/api/origination/*`, `/s/` and public signing routes
and Django route names remain available. Old Python module imports are thin
compatibility aliases; new code imports the owned app directly. Telegram launcher
and onboarding projections consult independent Origination capabilities. This
change does not publish a launcher or send Telegram invitations or messages.

## Reference contract

`core.services.workflow_links` declares immutable, allowlisted adapters for
Origination, Complaints, TAT, Portal, SPIN, farmer intake, FCA review and Order
Approval. Existing projections add a `record_ref`, for example:

```json
{"version": 1, "app": "loan_origination", "entity": "application", "id": "00000000-0000-0000-0000-000000000001"}
```

References contain no name, national ID, phone, evidence URL or signing token.
They confer no access. `resolve_record`, `describe_record` and `launch_record`
recheck current authorization and fail with the same safe error for unknown,
removed or unauthorized records. TAT soft deletions and closed Pilot visibility
remain enforced. Legacy review apps are marked as requiring their existing
review session; the registry never mints or exposes review tokens.

Launch descriptors use existing entry routes; Portal can target its existing
case-history route. This release has no link database, related-record UI,
identity suggestions, automatic customer joins or cross-app workflow handoffs.
Future link actions must independently require authorized editors in both owning
apps, a reason, revision/idempotency protection and append-only audit evidence.
Shared identity or a reference alone must never grant access or trigger a transition.

## Operator rollout and rollback

Stop admission of writes and record a verified database backup before schema
changes. Inspect the migration plan, then apply all apps together:

```powershell
.venv/Scripts/python.exe manage.py migrate --plan
.venv/Scripts/python.exe manage.py migrate --noinput
.venv/Scripts/python.exe manage.py check
.venv/Scripts/python.exe manage.py makemigrations --check --dry-run
.venv/Scripts/python.exe manage.py collectstatic --noinput
```

The new migrations are `core.0199`, `core.0200`, and `origination.0001`–`0003`.
Ownership is a reversible state-only transfer; the only new operational column
is nullable application group scope. PostgreSQL comments are installed by a
checked-in migration. A conflicting pre-existing Origination content type stops
the transfer for audited reconciliation rather than deleting permission evidence.

While writes remain stopped, the schema rollback is:

```powershell
.venv/Scripts/python.exe manage.py migrate core 0198_physical_scan_replacement --plan
.venv/Scripts/python.exe manage.py migrate core 0198_physical_scan_replacement --noinput
```

Restore the previous code and static assets before resuming service. Rollback
preserves records, document bytes, hashes, content-type IDs and permission IDs.
It removes the new group column: applications created after rollout would lose
that scope unless restored from the verified backup. Independent grant/policy
evidence and informative PostgreSQL comments are retained; previous code ignores
the new workflow. No migration, deployment or production side effect was performed
during implementation.

## Verification

The checked-in ownership test exercises real migration upgrade and reversal with
synthetic application/document/permission evidence. CI includes Origination in
coverage, correctness checks and its PostgreSQL job. Local verification uses
isolated SQLite and blocked external connections; SQLite cannot validate actual
PostgreSQL comments. External signing, Telegram, Sheets and Drive operations are
tested through existing mocks and were not executed against live services.

Local results: all 13 activity browser checks, both signing browser checks,
13 launcher tests, 29 boundary/catalogue/safe-workflow checks and the real
ownership upgrade/rollback test passed. JavaScript syntax passed for 91 files;
Django system checks and migration consistency passed. The broad 259-test
current-schema probe passed 247 tests; six additional failures needed migration
seed data. Rerunning those and the nine new boundary tests against a fully
migrated database left only six failures reproduced on unchanged commit
`092ead8` (three template-add display expectations, the old product-bound upload
fixture, an empty supporting-document form contract and a demo application
without a governed product version). See `KNOWN_GAPS.md` for the remaining
repository-wide release gate failures. These results do not claim a green full
release gate or production PostgreSQL verification.

The activity renderer now presents plain **Field: old → new** lines across Portal,
Complaints and TAT. It removes comparison accordions and technical missing-history
messages; long notes are shortened for readability, while backend audit facts stay
unchanged.
