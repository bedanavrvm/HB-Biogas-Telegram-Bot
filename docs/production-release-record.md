# Production Release Record

Use one completed copy of this record for every production deployment. Keep
the completed record in the approved private operations location, not in Git.

## Identification and authority

- Release date and planned start time (Africa/Nairobi):
- Release owner and go/no-go authority: Bedan
- Release commit / Render deploy ID:
- `APP_RELEASE` / durable `ProductionReleaseAudit.release_id`:
- Previous known-good production commit / Render deploy ID:
- Production database migration state before release:
- `RELEASE_BACKUP_REFERENCE` (immutable provider ID; no signed URL or secret):
- If non-production has no backup, `RELEASE_ALLOW_NO_BACKUP=True` approval and
  recorded `no-backup:<environment>` evidence:
- Backup timestamp, provider, and restore-to-staging evidence:
- `RELEASE_ACTOR` and `RELEASE_ENVIRONMENT`:

## Pre-deploy evidence

- `check_production_readiness --strict` (all five Mini App auth gates and ages,
  Telegram webhook secret, signing credentials, conditional-consent policy,
  access-grant governance, strict Mini App idempotency, and legacy-write
  observation window):
- Legacy Mini App write aggregate is clear for the agreed observation window:
- JSON, multipart, and XHR idempotency client test result:
- `check_tat_production_readiness --strict` and JSON evidence:
- Latest successful TAT notification processor run / scheduler alert owner:
- First successful scheduler run observed while all enabled TAT groups were in shadow mode:
- Latest successful complaint-import runner heartbeat / scheduler alert owner:
- Latest successful TAT-repair runner heartbeat / scheduler alert owner:
- Durable runner shadow limits, stale-lease recovery, retry, and cancellation evidence:
- TAT mode, group, Sheet-contract, access, responsibility, and private-connection review:
- `check_business_admin_cutover --strict`:
- `verify_compliance_audit --strict`:
- `sample_compliance_audit --strict`:
- CI run URL / full test result:
- Staging migration result:
- Telegram staging smoke test (JBL Officer, Credit Analyst, Business Admin):
- TAT staging modes: shadow / group / private / backup escalation:
- Read-only Sheets/register and Drive-link smoke test:
- `inspect_release_migration_plan --json` migration names and SHA-256:
- Enabled Origination signing readiness result:

## Production verification

- `release.sh` pre-deploy result:
- Durable release-audit status, attempt count, and Admin evidence review:
- Migration state after release:
- `/api/health/` result:
- Protected readiness result:
- Authorized Portal read-only case flow:
- Private workspace action:
- TAT queue, search, pagination, update, private link, and group fallback result:
- Read-only existing register/document-link result:
- Opened to all authorized staff at:

## Monitoring and rollback decision

- Sentry / Render alert coverage confirmed until:
- Same-path 5xx events during first 15 minutes:
- Authorization, audit-integrity, payment/approval, or external-write anomalies:
- Go, halt, forward-fix, or rollback decision and reason:
- Response classification: application rollback / forward-only corrective migration / approved disaster-recovery restore:
- Application rollback compatibility or corrective migration review evidence:
- If database restore: incident approval, exact backup reference, and accepted data-loss window:
- Next-business-morning review result:
