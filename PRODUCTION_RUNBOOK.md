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
5. Set `RELEASE_BACKUP_REFERENCE` to the immutable provider backup/snapshot ID,
   `RELEASE_ACTOR` to the deployment actor or automation identity, and
   `RELEASE_ENVIRONMENT=production`. These values are audit metadata, not
   secrets. Never put a signed backup URL, credential, or access token in them.
6. Configure the production Telegram webhook secret and service-account access only after the application has passed its readiness check.

`release.sh` delegates to `release_production`. The command runs general,
enabled TAT, and enabled Origination signing readiness before it inspects the
migration plan and verifies the backup reference. Only then can it migrate. It
runs Django's deploy check after migration, skips Superuser bootstrap if that
check fails, and records a secret-free `ProductionReleaseAudit`. It deliberately
does **not** contact Telegram or Google. Run `python manage.py
sync_telegram_commands` only as an explicit, reviewed operation after confirming
the group configuration; use `--dry-run` first.

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
5. Before production, confirm the PostgreSQL backup completed, copy its immutable
   provider reference into `RELEASE_BACKUP_REFERENCE`, preserve a copy/version
   of any affected Google Apps Script and Sheet layout, and set `APP_RELEASE` to
   the exact production commit/deploy ID.
6. Deploy with `bash release.sh` as the pre-deploy command. After the new service is healthy, verify `/api/health/`, an authorized Mini App read flow, and webhook delivery without exposing customer data in the test.
7. Monitor Render logs, Sentry, webhook errors, and unsynced integration records for at least one hour. Record the result in the release ticket.

To inspect exactly what would migrate without applying anything, run:

```powershell
python manage.py inspect_release_migration_plan --json
```

For supervised execution, `python manage.py release_production` accepts
`--release-id`, `--backup-reference`, `--actor`, and `--environment`. Command-line
values override deployment configuration, but they must remain non-secret. A
retry with the same release ID is safe after migrations complete: an empty plan
does not invoke `migrate`, the post-check and idempotent bootstrap run again, and
the earlier migration list and attempt history remain in the audit record.
Once the audit table exists, the command reserves the reviewed plan immediately
after all preflights and backup validation pass, so a migration or worker failure
cannot lose the planned migration names. This reservation never occurs after a
failed readiness or missing-backup check.

### Rollback and correction decision

Record one of these distinct responses before release; they are not
interchangeable:

- **Application rollback:** redeploy the recorded known-good application build.
  This does not reverse database migrations. Use it only when the older code is
  compatible with the migrated schema, and verify a read-only workflow first.
- **Forward-only corrective migration:** the normal response to a schema or data
  defect after migration. Preserve evidence, deploy a reviewed additive repair,
  and do not erase immutable workflow/audit history. This is preferred for
  approval, financial, audit-ledger, and integration state.
- **Database restore:** disaster recovery only, with explicit incident authority.
  Stop writers, identify the exact `RELEASE_BACKUP_REFERENCE`, document the
  accepted data-loss window, restore into staging first when possible, and then
  restore the complete production database under provider/operator supervision.

Do not automatically reverse migrations when a post-migration check fails. The
release command records `post_check_failed`, blocks bootstrap and application
promotion, and exits non-zero. Investigate whether application rollback or a
forward corrective migration is safe; use database restore only for an
explicitly approved disaster-recovery event.

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

There is no Celery/Redis worker. The approved platform scheduler runs TAT
private notifications, durable complaint imports, and bounded TAT repairs from
their management commands. The latter two use database leases and per-item
checkpoints; HTTP/Admin requests only queue work. Configure and monitor them as
described in `docs/tat-production-runbook.md` and
`docs/durable-job-runners.md`. Other retryable/dead-letter records remain
operator-controlled. Do not delete a local case/document or claim a sync
succeeded because an external call failed.

Keep `REQUIRE_MINIAPP_IDEMPOTENCY_KEY=True` in production. Before release,
review the anonymous legacy-write warning over
`MINIAPP_IDEMPOTENCY_OBSERVATION_DAYS`, verify the first-party clients in real
Telegram sessions, and investigate any route that still records missing-key
attempts. Production readiness fails if strict mode is disabled; local/test
compatibility mode is not a production bypass.

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

### Staff lifecycle decisions

Use **Authentication and Authorization > Users > Staff lifecycle workspace**
for ordinary staff onboarding, permanent access, transfer, leave, return, and
offboarding.

- **Review and apply now** is the normal active-Superuser path. Review the exact
  server-generated impact, re-enter the current Admin password, and confirm.
  No checker is required.
- **Send for independent review** is optional. Appointed checkers open the
  dedicated **Configuration > Staff approvals (N)** queue to approve or reject.
- For an existing pending plan, an active Superuser may open it and
  password-confirm **Apply now** or **Cancel plan**.
- A repeated identical request returns the original plan; a changed request
  must use a new request key. Never work around a conflict with direct ORM
  AccessGrant writes.

After deploying this behavior, apply migration
`core.0143_direct_superuser_staff_lifecycle` before exercising the workspace.
Verify one synthetic direct onboarding, one identical retry, and one optional
review in staging. Confirm the decision mode and actor appear on the plan and
in compliance evidence, then remove the synthetic users through the approved
hard-delete process if required.

### Superuser user hard deletion

Use **Authentication and Authorization → Users → Hard delete account** (or the
bulk action) only when the account must be physically removed. This is a
unilateral active-Superuser operation and does not enter the staff-lifecycle
checker queue.

1. Review every retained, detached, and deleted relationship in the preview.
2. Confirm at least one other active Superuser will remain.
3. Choose a specific reason category, add useful context, re-enter your Admin
   password, and type the displayed confirmation phrase exactly.
4. After completion, open the recorded `UserHardDeletionBatch`, review its TAT
   coverage gaps, and assign replacement access/responsibility where required.
5. Run `python manage.py verify_compliance_audit --strict` and retain the result
   with the release/incident evidence.

Hard deletion does not remove signed documents, applications, decisions, or
compliance events. It does remove live access, personal UI state, task locators,
and delivery connections. A deleted account is not recoverable through Admin;
restore an approved backup or onboard a new account deliberately.
