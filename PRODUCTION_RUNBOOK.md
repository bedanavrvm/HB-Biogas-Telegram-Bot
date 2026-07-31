# Production Runbook

This is the operational source of truth for releasing and maintaining the JBL/Jawabu workflow platform. Django owns workflow state; Google Sheets and Drive are integrations, not the database.

## Environment separation

Maintain separate **staging** and **production** Render services, PostgreSQL databases, Telegram bots/groups, service accounts, Google Sheets, and Drive folders. Staging uses only synthetic data and copied sheet layouts. Do not point a local machine or staging service at production resources.

Protect `main`: use a feature branch and pull request for every change, require GitHub Actions to pass, and tag or record the production commit before every deployment.

## Initial production setup

1. Use Render PostgreSQL and enable automated daily backups. Perform a restore into staging before launch and at least quarterly thereafter.
2. Put all secrets in Render environment variables or secret files. Configure the production values represented in `.env.example`; do not upload `.env` or a Google service-account JSON to Git. HSTS preload is enabled: use only an HTTPS-only domain whose subdomains are also safely served over HTTPS.
3. Use Render's **pre-deploy command**: `bash release.sh`. Use the normal start command: `bash start.sh`.
4. Create a Sentry **Django** project for the production service. In Sentry,
   enable an alert for new unresolved errors to the release owner and enable
   the project privacy option that prevents storing IP addresses. Set
   `SENTRY_DSN` only in Render's secret environment configuration,
   `SENTRY_ENVIRONMENT=production`, and `APP_RELEASE` to the Git commit or
   Render deploy ID. Keep `SENTRY_TRACES_SAMPLE_RATE=0.0` until a separate
   performance-monitoring and data-minimisation decision is approved. Point
   external uptime monitoring at `GET /api/health/`.
5. Configure the production Telegram webhook secret and service-account access only after the application has passed its readiness check.

`release.sh` runs configuration validation, migrations, and the idempotent superuser setup. It deliberately does **not** contact Telegram. Run `python manage.py sync_telegram_commands` only as an explicit, reviewed operation after confirming the group configuration; use `--dry-run` first.

The application strips request bodies, query strings, cookies, headers,
user identity, and arbitrary extras before Sentry receives an error event.
After adding the DSN in staging, generate one synthetic staging exception and
confirm Sentry displays only the environment, release, exception, request
method, and query-free path. Never test monitoring with customer data.

## Standard release

1. Define the change, affected workflows, migration impact, sheet/Apps Script impact, and rollback commit in the pull request. Obtain explicit approval before a production Render deploy, production migration, permission/access-policy change, external dependency, or action affecting payments/disbursements.
2. Run the focused test suite, then `python manage.py test`, `python manage.py check`, `python manage.py makemigrations --check --dry-run`, `python manage.py collectstatic --noinput`, and `python manage.py check --deploy`.
3. Test every changed Mini App on a narrow mobile viewport with loading, empty, error, authorization, slow-network, and double-submit cases.
4. Deploy to staging and perform an end-to-end test with the staging bot and copied Sheets/Drive resources.
5. Before production, confirm the PostgreSQL backup completed, preserve a copy/version of any affected Google Apps Script and Sheet layout, and record the current production commit.
6. Deploy with `bash release.sh` as the pre-deploy command. After the new service is healthy, verify `/api/health/`, an authorized Mini App read flow, and webhook delivery without exposing customer data in the test.
7. Monitor Render logs, Sentry, webhook errors, and unsynced integration records for at least one hour. Record the result in the release ticket.

### Migration rollback record

Every schema migration must include its exact rollback command in the release
record before it is applied. Confirm first whether a forward data repair is
safer than destructive reversal. Never apply a migration merely because it
exists in the source tree; production application requires explicit approval
for that release.

For the current Portal release, record the actual production migration state
first. If `core.0089_portalcaseworkspace_portalsavedview` is the only migration
being reversed, its safe schema rollback is:

```powershell
python manage.py migrate core 0088_business_admin_role_cutover
```

Do not treat that command as a rollback for the earlier cumulative release
migrations. In particular, run `python manage.py check_business_admin_cutover
--strict` before applying or reversing the `0088` Business Administrator
cutover. Approval, audit-ledger, and integration migrations require an
incident-specific forward correction or a reviewed restore-to-staging plan.

Use the current release record template in
[`docs/production-release-record.md`](docs/production-release-record.md) to
capture the baseline, approval, verification evidence, and rollback decision.

## Sheets, Drive, and Apps Script

- Make schema/formula/conditional-format changes on a copied sheet first. Preserve header rows, formula-owned fields, and staff-owned fields.
- Run `node --check` on changed `.gs` files. Deploy Apps Script to the test copy, test it, then manually deploy the reviewed version to production.
- Never change a sheet in a way that makes the running Django version unable to read or write it. Use additive, backward-compatible changes and deploy code plus sheet changes as one planned release.
- Google/Drive failures must leave the Django record and audit history intact. Retry through the approved operation, not by re-creating customer records.

## Integration operations and readiness

Keep `GET /api/health/` as the public liveness check. It performs a DB-only
probe. `GET /api/readiness/` requires `API_AUTH_TOKEN` and reports local DB,
migration, durable-operation, and circuit state without contacting Google,
Drive, or Telegram.

Before a supervised integration maintenance window, run the configuration-only
check:

```powershell
python manage.py probe_integrations
```

Only after explicit approval for read-only external calls, run:

```powershell
python manage.py probe_integrations --execute
```

The retry/circuit tables are an operator-visible register, not a background
queue. There is no Celery/Redis worker or scheduler. Review retryable/dead-
letter records in Django Admin and retry through the owning workflow after the
external dependency is healthy. Do not delete a local case/document or claim a
sync succeeded because an external call failed.

Before enabling `REQUIRE_MINIAPP_IDEMPOTENCY_KEY=True`, verify current Portal,
Complaint Cases, TAT, and SPIN Mini Apps in real Telegram clients and obtain
explicit approval. The setting blocks old cached clients that do not send a
retry key.

## Recovery

For an application fault, revert to the recorded Git commit and redeploy; verify health and a read-only workflow first. Do not blindly reverse database migrations. For a data incident, stop the affected write path, preserve logs/audit data, restore into staging, choose a forward corrective migration or controlled data repair, then review before production execution.

Rotate a suspected credential immediately at its provider and update Render. Removing it from Git does not invalidate it. Escalate webhook delivery failures, repeated authorization errors, Google quota failures, and health-check failures immediately.

## Evidence cadence and emergency access

### Compliance audit evidence

The cross-workflow compliance ledger is append-only evidence, separate from
Sentry and ordinary application logs. Before every production release that
changes Portal, Complaint Cases, TAT, SPIN, documents, or access policy, run:

```powershell
python manage.py verify_compliance_audit --strict
python manage.py sample_compliance_audit --strict
```

Create a local daily checkpoint only through the supervised operation below;
it does not send email:

```powershell
python manage.py checkpoint_compliance_audit --apply
```

Do not use `--deliver` until an approved controlled compliance mailbox,
Render mail configuration, recipient owner, retry response, and staging test
are recorded. The PostgreSQL trigger prevents application-role modification of
ledger entries, but a database owner can still alter database objects. Keep the
independent checkpoint and integrity-verification evidence with the release
record. Do not create any automatic audit-retention purge until JBL has an
approved, legally validated retention schedule.

### Backup targets and restore drills

The operational targets below are not evidence of a successful restoration.
Record each actual drill date, backup timestamp, elapsed recovery time, owner,
and result in the release/operations record.

| Store | RPO target | RTO target | Drill cadence |
|---|---:|---:|---|
| Render PostgreSQL | 24 hours | 4 hours | Quarterly restore to staging |
| Google Sheets / Drive | 24 hours | 8 hours | Quarterly copied-resource restore to staging |

Do not claim either target is met until the target service has a recorded
successful drill. Sheets and Drive are operational integrations, so preserve
versioned layouts/files as part of every relevant release.

### Secrets

Rotate production Telegram, Django, Google, Sentry, and manual API credentials
at least quarterly and immediately after a suspected exposure or staff-access
incident. Record the date, owner, provider, and validation result in the
approved private operations record—not in this repository. Render environment
variables/secret files are the approved production store.

### Emergency access

Use the Django Admin **Emergency access** action only for an approved,
time-sensitive operational need. Supply a specific reason, scope it to the
smallest workflow/branch/product, verify its automatic expiry, and review the
`EmergencyAccessGrant` and notification audit rows afterward. It creates
temporary audited access; use the maker-checker access request flow for any
permanent change.
