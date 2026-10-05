# Scheduled Portal reports through Resend

## Context

Staff need recurring Pipeline, Outcomes and Finance reports without spreadsheet editing. Email recipients may not have Portal accounts, so a mailing list alone is insufficient authorization for customer-level exports.

## Decision

The bounded `report_delivery` app owns approved, explicitly scoped recipients, schedules and durable recipient deliveries. Active Superusers or Portal IT grants authorize configuration and every send. A single IT grant must encompass the entire requested group/branch/product scope; grants are never combined to widen it. The existing Portal report catalogue supplies data. One repeatable-read capture supplies the summary, PDF and Excel attachments.

A scheduled Django command reserves the latest due occurrence, leases work and calls Resend's HTTPS API. No request thread sends email. Exact payloads and provider idempotency keys survive retries. Unknown submission outcomes beyond Resend's 24-hour key lifetime require operator reconciliation rather than automatic resubmission. Signed webhooks update delivery evidence and suppress bounced or complained-about addresses. Sending is disabled by default.

## Consequences

Operators provision the verified sending domain, secrets, webhook and minute-based command. Payloads expire after 30 days; delivery metadata expires after 180 days. Email delivery is not proof that somebody read a report. External delivery does not change any Portal workflow state.

## Alternatives considered

Workspace SMTP/Gmail would couple report delivery to an unrelated appraisal integration. Browser timers and process-local threads lose work on restart. A new queue service would add infrastructure unnecessarily; database leases and a bounded command match existing durable runners.

## Migration and rollback

Migrations `report_delivery.0001_initial` and `0002_alter_approvedrecipient_authorized_by_and_more` create new tables and delivery-correlation indexes, with nullable approving-actor references so staff hard deletion revokes sends instead of being blocked. Before rollback, disable sending, stop the runner and export configuration/history if required. Reverse with `python manage.py migrate report_delivery zero`; this deletes this app's configuration and retained delivery evidence, not cases or external emails. Reapply with `python manage.py migrate report_delivery`. No production migration is applied by this change.
