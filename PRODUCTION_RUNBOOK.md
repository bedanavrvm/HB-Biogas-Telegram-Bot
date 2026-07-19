# Production Runbook

This is the operational source of truth for releasing and maintaining the JBL/Jawabu workflow platform. Django owns workflow state; Google Sheets and Drive are integrations, not the database.

## Environment separation

Maintain separate **staging** and **production** Render services, PostgreSQL databases, Telegram bots/groups, service accounts, Google Sheets, and Drive folders. Staging uses only synthetic data and copied sheet layouts. Do not point a local machine or staging service at production resources.

Protect `main`: use a feature branch and pull request for every change, require GitHub Actions to pass, and tag or record the production commit before every deployment.

## Initial production setup

1. Use Render PostgreSQL and enable automated daily backups. Perform a restore into staging before launch and at least quarterly thereafter.
2. Put all secrets in Render environment variables or secret files. Configure the production values represented in `.env.example`; do not upload `.env` or a Google service-account JSON to Git. HSTS preload is enabled: use only an HTTPS-only domain whose subdomains are also safely served over HTTPS.
3. Use Render's **pre-deploy command**: `bash release.sh`. Use the normal start command: `bash start.sh`.
4. Set `APP_RELEASE` to the Git commit or Render deploy ID, configure `SENTRY_DSN`, and point external uptime monitoring at `GET /api/health/`.
5. Configure the production Telegram webhook secret and service-account access only after the application has passed its readiness check.

`release.sh` runs configuration validation, migrations, and the idempotent superuser setup. It deliberately does **not** contact Telegram. Run `python manage.py sync_telegram_commands` only as an explicit, reviewed operation after confirming the group configuration; use `--dry-run` first.

## Standard release

1. Define the change, affected workflows, migration impact, sheet/Apps Script impact, and rollback commit in the pull request.
2. Run the focused test suite, then `python manage.py test`, `python manage.py check`, `python manage.py makemigrations --check --dry-run`, `python manage.py collectstatic --noinput`, and `python manage.py check --deploy`.
3. Test every changed Mini App on a narrow mobile viewport with loading, empty, error, authorization, slow-network, and double-submit cases.
4. Deploy to staging and perform an end-to-end test with the staging bot and copied Sheets/Drive resources.
5. Before production, confirm the PostgreSQL backup completed, preserve a copy/version of any affected Google Apps Script and Sheet layout, and record the current production commit.
6. Deploy with `bash release.sh` as the pre-deploy command. After the new service is healthy, verify `/api/health/`, an authorized Mini App read flow, and webhook delivery without exposing customer data in the test.
7. Monitor Render logs, Sentry, webhook errors, and unsynced integration records for at least one hour. Record the result in the release ticket.

## Sheets, Drive, and Apps Script

- Make schema/formula/conditional-format changes on a copied sheet first. Preserve header rows, formula-owned fields, and staff-owned fields.
- Run `node --check` on changed `.gs` files. Deploy Apps Script to the test copy, test it, then manually deploy the reviewed version to production.
- Never change a sheet in a way that makes the running Django version unable to read or write it. Use additive, backward-compatible changes and deploy code plus sheet changes as one planned release.
- Google/Drive failures must leave the Django record and audit history intact. Retry through the approved operation, not by re-creating customer records.

## Recovery

For an application fault, revert to the recorded Git commit and redeploy; verify health and a read-only workflow first. Do not blindly reverse database migrations. For a data incident, stop the affected write path, preserve logs/audit data, restore into staging, choose a forward corrective migration or controlled data repair, then review before production execution.

Rotate a suspected credential immediately at its provider and update Render. Removing it from Git does not invalidate it. Escalate webhook delivery failures, repeated authorization errors, Google quota failures, and health-check failures immediately.
