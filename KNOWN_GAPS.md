# Known Gaps and Verified Workarounds

Last reviewed: 29-July-2026

## Cross-workflow customer data cleanup

The governed customer-resolution rollout currently covers active Jawabu cases
and staged `/sysup` system exports. Complaint Cases, TAT, and SPIN retain
their present records and validations until a separately approved migration
maps their identity fields into the same customer-resolution service. Run
`python manage.py audit_jawabu_data_quality --strict` before a controlled
Jawabu cleanup; the command is read-only and must not be mistaken for a merge
or backfill tool.

## Telegram WebView printing

Telegram's mobile WebView does not provide a dependable browser print stack;
live canvas/browser print previews can be blank. The supported workflow is:
preview the document values in-app, then use **Open Excel** to download/open
the generated workbook in a proper spreadsheet application for printing. Do
not reintroduce `window.print()` as a production document workflow without a
new verified Telegram-client test and ADR.

## Mini App recovery drafts

`core.0072_miniapp_drafts` is committed but not authorized for production
application. The feature requires verified Telegram identity and the form's
existing scoped authorization; it cannot promise an offline save. Offline
edits remain in the current open screen and become durable only after the UI
shows that the server saved the draft. Attachments are intentionally excluded.

Required verification before release:

1. Explicit approval to deploy and apply the migration.
2. A real Telegram mobile test for SPIN, FCA, FarmUp, and System Export draft
   restore, conflict behaviour, expiration, and attachment re-selection.
3. Confirmation that `release.sh` runs the migration against the intended
   database only.

### Order Approval browser draft remains

During the draft audit, `core/templates/order_approval/form.html` was found to
retain its own browser-local recovery draft. It was not converted in this
change because its form-token/Telegram authorization path and customer/media
field boundary need a dedicated review before server persistence is introduced.
Do not copy that local-storage pattern into another Mini App. A follow-up must
reuse the `MiniAppDraft` service only after it has a capability/scoped-token
authorization test and confirms attachments stay out of the draft.

## Workflow SLA delivery

The workflow-integrity command records or previews overdue-stage escalations
without sending Telegram messages by default. This is intentional: automatic
notification delivery needs approved recipient routing, rate-limit/backoff
handling, and an explicitly approved Render schedule. Until that operating
change is approved, run the command in dry-run mode and use the resulting
pending escalation records for supervised follow-up.

## Business-calendar and TAT trend operations

Official TAT/SLA time now excludes only dates entered and kept active in Django
Admin under **Business calendar holidays**. The platform deliberately does not
download Kenya public holidays from an external source, so an authorised
operator must confirm the year’s dates before relying on SLA reporting. Run
`python manage.py snapshot_workflow_tat --json` to review the current
projection; `--apply` is an internal, idempotent database write and still
needs an explicitly approved scheduler before it becomes a routine job.
Individual trend rows are emitted only where a workflow has recorded a named
responsible actor. They must be interpreted with the recorded branch, role,
product and paused/deferred-time context; absent attribution stays
role/branch-level rather than being guessed.

## Backup and recovery evidence

The production runbook requires Render daily PostgreSQL backups and quarterly
restore drills, but this repository contains no recorded successful drill or
measured recovery time. Treat the following as operating targets, **not proven
service levels**, until a drill is recorded:

| Store | RPO target | RTO target | Evidence required |
|---|---:|---:|---|
| PostgreSQL | 24 hours | 4 hours | Restore a current backup to staging and record elapsed time. |
| Google Sheets / Drive | 24 hours | 8 hours | Restore a copied/versioned spreadsheet or Drive document to staging and record the result. |

No production data reset, destructive Sheet cleanup, or migration is routine
until the relevant recovery path has been checked.
