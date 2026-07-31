# Production Release Record

Use one completed copy of this record for every production deployment. Keep
the completed record in the approved private operations location, not in Git.

## Identification and authority

- Release date and planned start time (Africa/Nairobi):
- Release owner and go/no-go authority: Bedan
- Release commit / Render deploy ID:
- Previous known-good production commit / Render deploy ID:
- Production database migration state before release:
- Backup timestamp, provider, and restore-to-staging evidence:

## Pre-deploy evidence

- `check_production_readiness --strict`:
- `check_business_admin_cutover --strict`:
- `verify_compliance_audit --strict`:
- `sample_compliance_audit --strict`:
- CI run URL / full test result:
- Staging migration result:
- Telegram staging smoke test (JBL Officer, Credit Analyst, Business Admin):
- Read-only Sheets/register and Drive-link smoke test:

## Production verification

- `release.sh` pre-deploy result:
- Migration state after release:
- `/api/health/` result:
- Protected readiness result:
- Authorized Portal read-only case flow:
- Private workspace action:
- Read-only existing register/document-link result:
- Opened to all authorized staff at:

## Monitoring and rollback decision

- Sentry / Render alert coverage confirmed until:
- Same-path 5xx events during first 15 minutes:
- Authorization, audit-integrity, payment/approval, or external-write anomalies:
- Go, halt, forward-fix, or rollback decision and reason:
- If rollback: application commit reverted to / migration decision / evidence:
- Next-business-morning review result:
