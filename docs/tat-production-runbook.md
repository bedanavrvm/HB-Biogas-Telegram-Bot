# TAT Mini App Production and Maintenance Runbook

This runbook supplements `PRODUCTION_RUNBOOK.md`. It covers the TAT-specific
release gate and never authorizes production Telegram or Google side effects by
itself.

## Required production services

- Django web service and PostgreSQL database.
- Production Telegram bot, webhook, BotFather Mini App short name, and approved
  TAT group.
- Governed Google Sheet register contract for every enabled TAT group.
- Render Cron Job or equivalent durable scheduler running once per minute:

```text
python manage.py process_tat_notifications --limit 100
```

The command uses a database lease, so overlapping invocations are skipped
safely. It records aggregate run health in **TAT notification processor runs**
without case or customer data. Configure the scheduler platform to alert on a
non-zero exit. Sentry captures the server exception. After strict enforcement
is enabled, the TAT readiness check fails after three minutes without a
successful run by default.

## Pre-production configuration

1. Configure the BotFather URL and ensure `TAT_TRACKER_MINI_APP_SHORT_NAME`
   matches it. Require Telegram authentication.
2. Configure each enabled TAT group, copied/tested Sheet layout, products,
   branches, targets, and notification mode.
3. Seed and review the publication-only Sheet contract on a copied Sheet first.
4. Apply `AccessGrant` records through the approved access-control process.
5. Assign one unambiguous primary and optional ranked backups for every active
   group/branch/product/stage scope.
6. Have nominated staff connect private alerts from the Mini App.
7. Change TAT data mode from Pilot to Production only after rehearsal and
   business authorization.

## First scheduler bootstrap

The health table does not exist before this release's migration, so the first
deploy is intentionally two-stage:

1. Put every enabled TAT group in `shadow` mode and deploy with
   `TAT_NOTIFICATION_SCHEDULER_REQUIRED=False`.
2. Apply migrations and provision the one-minute scheduler. Shadow processing
   records what would be delivered without sending private Telegram alerts.
3. Confirm at least one successful processor run and no repeated overlap,
   stale-lock, retry, overdue, or unreachable-recipient condition.
4. Set `TAT_NOTIFICATION_SCHEDULER_REQUIRED=True`, redeploy, and run the strict
   readiness gate. Do not enable `hybrid` private delivery until staging
   acceptance and business authorization are recorded.

## Release gate

Run the generic release checks and migrations, then:

```powershell
python manage.py check_tat_production_readiness --strict
python manage.py check_tat_production_readiness --json
```

The readiness command is read-only and makes no Telegram or Google request. It
checks migrations, Mini App authentication configuration, Production mode,
groups, Sheet contracts, access coverage, routing ambiguity, primary private
connections, scheduler freshness, and expired locks.

Do not invoke `process_tat_notifications` manually against production merely as
a health probe: outside shadow mode it may send due Telegram alerts. Use the
record created by the approved scheduler.

Record the result in `docs/production-release-record.md`. Do not waive missing
access, ambiguous routing, a stale scheduler, an untested backup, or a failed
full test suite.

## Staging acceptance

Use synthetic cases, a staging bot/group, and copied Sheets. Verify every role
and both allowed and forbidden branch/product scopes. Exercise:

- create and update replay, stale revision, and stale data-mode conflicts;
- queue pagination, search, back navigation, and 320/390 px layouts;
- shadow routing, existing group alerts, private delivery, transient retry,
  unreachable primary, ranked backup escalation, and cumulative group fallback;
- expired/superseded deep links, Telegram background/resume, and Sheet outage;
- PostgreSQL and copied-Sheet restoration, with measured recovery time.

## Monitoring and maintenance

- Run the scheduler every minute. Alert after three minutes without success.
- Review failed/skipped runs, retry and overdue counts, unreachable recipients,
  group exception status, responsibility health, and Sheet sync failures.
- A skipped overlap is harmless when the owning run completes. Repeated skips
  or `stale-lock-recovered` means runtime or scheduler overlap needs attention.
- Correct access through the maker-checker access process. Correct routing in
  responsibility assignments. Ask the user to reconnect private alerts when
  delivery is blocked; do not broaden access to make delivery succeed.
- Keep run health for 90 days by default. It contains aggregate operational
  evidence only.

## Halt and rollback

To stop new private delivery during an incident, change affected TAT groups to
`shadow` or `group` mode through the controlled configuration path and suspend
the scheduler if necessary. Do not delete tasks, recipients, cases, events, or
run evidence. Revert application code to the recorded known-good release only
after checking migration compatibility. Restore data into staging first; use a
reviewed forward repair for production whenever possible.
