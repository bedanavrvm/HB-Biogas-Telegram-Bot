# Known Gaps and Verified Workarounds

## Personal notification delivery preferences

`UserMiniAppPreference.alert_mode` remains stored for backward compatibility,
but recipient-level Telegram delivery does not yet apply immediate, digest, or
quiet choices. The Mini Apps intentionally do not render that selector until a
delivery worker enforces the shared mandatory-alert catalogue. Assignment,
approval, security, and overdue-breach alerts are not suppressible.

## Sentry production verification

The Django SDK is pinned, installed, initialized from `SENTRY_DSN`, and tested
with a synthetic DSN. Render's strict production-readiness gate passed on
31-July-2026 after Sentry configuration. The remaining operator verification
is a safe staging synthetic exception: confirm its alert rule fires and that
the event contains no customer/staff payload.

## Business Administrator role cutover

`core.0088_business_admin_role_cutover` was applied in production by the
31-July-2026 recorded migration baseline. It renames effective Portal/TAT/SPIN workflow access from legacy
`ADMIN` to `BUSINESS_ADMIN`, without rewriting historical audit evidence. Run
`python manage.py check_business_admin_cutover --strict` before the production
migration; it blocks unresolved pending legacy access-policy requests or
duplicate effective grant scopes. Capability seed-row overlaps are merged by
preserving the existing allow/deny policy. To undo after a controlled release, run
`python manage.py migrate core 0087_repair_tat_stage_target_snapshot_backfill`;
the reverse migration stops if a legacy-role collision would make rollback
ambiguous.

## Access-control checker bootstrap

`core.0090_accesscontrolcheckerassignment` is accepted for code merge and
local/staging validation only. It records independent checker appointments and
backfills legacy approver-group members without changing Users, Access Grants,
workflow state, financial records, or Mini App access. Before any approved
production rollback, export checker appointment and compliance-audit evidence,
then run `python manage.py migrate core 0089_portalcaseworkspace_portalsavedview`.

## Portal private workspace hold

`core.0091_pause_portal_workspace_to_it` is accepted for code merge and
local/staging validation only. It preserves existing private saved views, pins,
and recents. The Portal Mini App does not render any workspace control for any
role, including IT. The retained endpoint remains IT-gated only for controlled
technical validation; it is not a staff-facing feature. The migration
increments the policy version when it creates policy rows, forcing connected
Mini Apps to refresh permissions on their next metadata poll. It does not
alter customer cases, financial values, Drive/Sheets, or workspace records.

Do not roll back application code to re-open this feature. A future UI
re-enable requires an explicitly approved rollout and the existing capability
review; it must preserve the IT server-side gate. The migration's reverse is
intentionally a no-op so policy and compliance evidence remain retained.

## Portal workspace migration and retention

`core.0089_portalcaseworkspace_portalsavedview` was applied in production by
the 31-July-2026 recorded migration baseline. It adds only private, user-owned saved-view and case-workspace
metadata; it never changes Jawabu cases, workflow state, financial values, or
audit evidence. Django live scope checks hide inaccessible/closed pins
immediately. Until an authorised scheduler is configured, an operator may run
the read-only preview `python manage.py prune_portal_workspace`, then the
explicitly approved `python manage.py prune_portal_workspace --apply` on the
agreed daily cadence to release pins unavailable for 30 days and remove
un-pinned recent metadata older than 90 days. To undo after an approved
release, run:

```powershell
python manage.py migrate core 0088_business_admin_role_cutover
```

The reverse migration drops only the two private workspace tables; it does not
alter case, workflow, financial, or audit tables.

## TAT Settings migration

`core.0085_tattrackercase_stage_target_snapshots_and_more`,
`core.0086_seed_tat_target_snapshots`, and
`core.0087_repair_tat_stage_target_snapshot_backfill` were applied in
production by the 31-July-2026 recorded migration baseline. They add user-owned Mini App
preferences, maker-checker TAT setting proposals, escalation-rule storage, and
target snapshots for active stages. Before any rollback, export approved
configuration requests for audit evidence. To undo the schema locally or after
an approved release, run `python manage.py migrate core 0084_integrationcircuitstate_integrationoperation`.

## Mini App notification preferences

TAT now stores an individual user's immediate/daily-digest/quiet preference
for non-critical alerts. Existing TAT stage alerts are still posted to the
configured shared Telegram group, not to individual recipients, so this
preference does not suppress, digest, or reroute those group alerts yet. A
recipient-level notification delivery ledger and scheduled business-day digest
job must be approved and implemented before enabling that behavior. Mandatory
assignment, security, approval, and overdue-breach alerts must remain outside
personal suppression in that future design.

## Bounded integration reliability

`core.0084_integrationcircuitstate_integrationoperation` was applied in
production by the 31-July-2026 recorded migration baseline. It records redacted external
operation/circuit state only; it does not start Celery, Redis, a scheduler, or
any automatic retry worker. Operators can run `probe_integrations` without
side effects for a configuration dry-run. `--execute` makes real read-only
metadata calls and must be an explicitly authorised maintenance action.

The current release routes shared Google Sheets batch writes, Drive uploads,
and Telegram launcher publishing through the durable register. Other legacy
direct outbound calls remain outside it and are listed in `TECH_DEBT.md`; they
must be migrated one bounded workflow at a time with replay tests. Strict Mini
App retry-key enforcement remains disabled until all refreshed cached clients
are verified in real Telegram clients. Do not set
`REQUIRE_MINIAPP_IDEMPOTENCY_KEY=True` during a production release without
that explicit verification and approval.

Last reviewed: 30-July-2026

## Compliance audit evidence

`core.0083_complianceauditchainstate_complianceauditcheckpoint_and_more` is
included in the pending release worktree but is not authorised for production
application. It adds an
append-only cross-workflow ledger, a PostgreSQL application-role immutability
trigger, read-only Admin investigation/export tools, and explicitly generated
daily checkpoint records. PostgreSQL database owners can still alter database
objects, so the ledger is tamper-evident rather than an absolute guarantee.

No automated retention deletion is implemented: every new compliance event is
on legal hold until JBL approves a legally validated retention schedule. No
mailbox delivery, scheduler, or scheduled sampling is enabled. Before enabling
those operations, approve a controlled recipient and mail configuration, test
the PostgreSQL trigger in staging, name an evidence owner, and record a tested
response path for failed delivery. Use `verify_compliance_audit --strict` and
`sample_compliance_audit --strict` only as supervised read-only checks.

## Sheet/Drive publication governance

`core.0082_sheet_register_governance` is committed but is not authorised for
production application. It adds local, publication-only Sheet contracts and
audit evidence; it does not alter Google Sheets/Drive or re-enable inbound
Sheet imports. Before relying on strict audit results, an authorised operator
must review each target tab and create contracts with
`python manage.py seed_sheet_register_contracts` (dry run) followed by the
explicit `--apply` only after the layout is confirmed. Run
`python manage.py audit_sheet_registers --strict` and
`python manage.py audit_drive_permissions --strict` as supervised read-only
checks. No scheduled audit, alert routing, automatic Drive-permission repair,
or periodic Sheets snapshot export is introduced; those need approved
recipients, a durable scheduler, rate-limit handling, and a retention design.

The TAT duplicate repair now verifies and re-publishes each linked survivor,
but it still deletes rows from the chosen live Sheet when `--apply` is used.
Use a copied Sheet first and keep the resulting `LiveSheetRecordChange` audit
evidence. A failed post-delete verification must be investigated manually; do
not rerun a destructive cleanup blindly.

## Portal approval controls and visit evidence

`core.0081_jawabuapprovalcondition_jawabuapprovaldelegation_and_more` is
committed but is not authorised for production application. Approval records,
conditions, temporary delegation, direct case-media links, and retrieval audit
are live only after the approved migration. Legacy farmer decisions and media
remain visible through compatibility reads; they are not retrospectively
asserted to meet the new evidence or authority controls.

The release deliberately does not delete Drive media. Run
`python manage.py audit_jawabu_visit_media --strict` to report unlinked
controlled evidence; it never changes attachments or Drive. Candidate review
and a separately approved retention/deletion policy are still required.
In-app SLA escalation remains an operational signal;
automatic Telegram/SMS/email delivery requires approved recipients, retry
handling, and a scheduled production job.

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

## Physical document signing

Requisitions and final payment schedules support retention of a physically
signed-and-stamped PDF/JPG/PNG scan. The system records the authorised staff
attestation, source-workbook hash, scan hash, and Drive outcome; it does **not**
verify handwritten signatures, stamps, or legal e-signature validity. The
external e-signature integration remains deliberately on hold. Existing
documents without locally retained source workbook bytes are legacy records and
must be regenerated before a new traceable physical sign-off can be attached.

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
