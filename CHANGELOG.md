# Changelog

## Workflow integrity - 30-July-2026

- TAT corrections are now explicitly update-only and retain one retry key for
  a failed/resubmitted correction. The new-loan form clearly distinguishes a
  separate loan from an existing case and shows exact National ID/phone loan
  context without blocking legitimate repeat loans.
- FarmUp review now requires a reason before an explicit additional unit is
  created. Additional-unit imports bypass the normal duplicate-key update
  fallback, allocate the next linked unit number, and record the reason in
  the case timeline.

## Reliability hardening - 30-July-2026

- Portal, Complaint Cases, TAT, and SPIN Mini App writes now accept a shared
  retry key while cached legacy clients remain supported until strict mode is
  explicitly enabled. Shared Google Sheets batch writes, Drive uploads, and
  Telegram launcher publishing leave redacted durable operation records and
  use bounded transient retry/circuit protection. Protected `/api/readiness/`
  reads stored status only; `probe_integrations` is manual and configuration-
  only unless an operator supplies `--execute`.

Migration `core.0084_integrationcircuitstate_integrationoperation` has **not**
been applied to production. It adds only local integration-operation/circuit
tables. To undo after an approved migration, export needed operation evidence,
then run:

```powershell
python manage.py migrate core 0083_complianceauditchainstate_complianceauditcheckpoint_and_more
```

This file records notable, user-visible and operational changes. Entries are
added while work is performed; deployment remains a separate, explicitly
approved action.

## Unreleased — 30-July-2026

- Audit & compliance: Portal, Complaint Cases, TAT, SPIN, document sign-off,
  and access-policy actions now project evidence into one append-only,
  hash-chained compliance ledger. Django Admin supports investigation filters,
  controlled CSV/PDF exports, and integrity verification; sensitive media and
  audit-log access/export events are recorded. Daily checkpoints are retained
  locally by an explicit command, while compliance-mailbox delivery remains
  disabled by default. No automatic retention deletion, external email, or
  production deployment is included.

Migration `core.0083_complianceauditchainstate_complianceauditcheckpoint_and_more`
adds the ledger, chain cursor, checkpoints, permissions, and a PostgreSQL
append-only trigger. It has **not** been applied to production by this change.
To undo after an approved migration, export required evidence, then run:

```powershell
python manage.py migrate core 0082_sheet_register_governance
```

- Render build reliability: the application build no longer runs `apt-get` in
  Render's read-only native build environment. The existing WeasyPrint PDF
  preflight remains, so a base-image library problem still fails clearly
  before deployment.

- Django startup and static collection are now quiet in Render builds: access
  catalog queries are deferred until their Admin forms are rendered, and the
  intentional django-unfold overrides of stock Django Admin assets no longer
  produce duplicate-file build noise.

- Sheets/Drive integration governance: Admin-managed publication contracts now
  define per-register header/field ownership, while explicit read-only audits
  record schema drift, row-pointer/value divergence, and media-root sharing
  posture without copying raw customer values. TAT duplicate-row cleanup now
  proves the surviving immutable Case ID after deletion and re-publishes the
  canonical case before it reports success; failed verification or re-publish
  is retained as failed local audit evidence.
  TAT publication contracts now resolve the runtime configuration by immutable
  Telegram group ID, so Mini App updates are not blocked by the in-memory
  `GroupConfig`/database foreign-key boundary.

Migration `core.0082_sheet_register_governance` adds the local contract and
audit evidence schema only. It has **not** been applied to production by this
change. To undo after an approved migration, export required audit evidence,
then run:

```powershell
python manage.py migrate core 0081_jawabuapprovalcondition_jawabuapprovaldelegation_and_more
```

- Portal approval and media integrity: credit, final-review, and payment-review
  decisions are now append-only, reason-coded approval records with 90-day
  validity, condition clearing, material-change invalidation, scoped temporary
  delegation, and a separate per-case payment review. A forward JBL visit now
  needs a LAF, a JBL visit photo, and captured location or a stated
  unavailability reason. New visit media uses a non-PII case storage reference
  and retrievals are auditable. `audit_jawabu_visit_media` reports orphan
  candidates without deleting or relinking Drive files.

Migration `core.0081_jawabuapprovalcondition_jawabuapprovaldelegation_and_more`
adds the approval/delegation/media-audit schema and seeds only
`portal.approval.delegation.authorize` for the current Portal `ADMIN` role. It
has **not** been applied to production by this change. To undo after an
approved migration, first export required approval/delegation/media audit
evidence, then run:

```powershell
python manage.py migrate core 0080_physical_document_signoffs
```

## Unreleased — 29-July-2026

- Documents & finance: generated requisitions and final payment workbooks can
  now retain an authorised, physically signed-and-stamped PDF/JPG/PNG scan
  without overwriting the Excel source. The scan and exact source workbook are
  hash-bound, Drive retries are auditable, and the responsible Portal role is
  maker-checker configurable. E-signatures remain intentionally disabled.

Migration `core.0080_physical_document_signoffs` adds retained payment source
bytes, document sign-off policy, append-only sign-off attempts/events, and the
Admin-only `portal.documents.sign` capability. It has **not** been applied to
production by this change. To undo after an approved migration, export any
sign-off evidence that must be retained, then run:

```powershell
python manage.py migrate core 0079_remove_workflowtatdailymetric_unique_workflow_tat_daily_metric_and_more
```

- Customer History and TAT: Portal and TAT now present a single internal
  chronological history for each case, including operational events, customer
  provenance, documents, decisions, corrections/redactions, accountable
  actors, and related customer units. Official SLA status now uses the shared
  Nairobi business calendar while retaining wall-clock time as context.
  Overdue work gains idempotent in-app escalation tiers and a dry-run daily
  trend snapshot command; no Telegram notifications or automated transitions
  are introduced.

Migrations `core.0078_businesscalendarholiday_and_more` and
`core.0079_remove_workflowtatdailymetric_unique_workflow_tat_daily_metric_and_more`
add the managed holiday calendar, append-only timeline annotations,
escalation accountability, and daily TAT projections with branch/role and
known-staff attribution. They have **not** been applied to production by this
change. To undo after an approved migration, preserve any required audit
evidence, then run:

```powershell
python manage.py migrate core 0077_seed_operational_products
```

- Jawabu data quality: `/sysup` and FarmUp now share governed customer identity
  normalization, retain historical phone observations, flag 7-9 digit ID
  exceptions for review, preserve system-export field provenance, and validate
  system products against one Admin-managed catalog. The Admin dashboard now
  reports active-case data-quality coverage and a dry-run command can audit
  active Jawabu cases or a staged `/sysup` batch without writing data.

Migration: `core.0076_governed_jawabu_data_quality` and
`core.0077_seed_operational_products` are required for governed phone history,
provenance, review evidence, and the product catalog. They have **not** been
applied to production by this change. To undo after an approved migration,
first export any provenance/review evidence that must be retained, then run:

```powershell
python manage.py migrate core 0075_tat_workflow_receipts
```

- Workflow integrity: Jawabu Pipeline and TAT now reject stale Mini App
  updates, record explicit transition metadata, preserve reasoned rework
  routes, and expose safe SLA-escalation dry runs. Payment approval behaviour
  and access-policy assignments are unchanged.

- Mini Apps: added shared touch-friendly controls, consistent status semantics,
  skeleton queue loading, Telegram haptic feedback, and session-only restoration
  of harmless Portal/Complaint queue context.
- FCA, FarmUp/System Export, and SPIN forms: replaced browser-local sensitive
  recovery drafts with short-lived, verified, server-owned field drafts. File
  attachments are intentionally excluded and must be selected at submission.
- Operations: added the shared glossary, ADR process, known-gap register, and
  repository operating standards for approvals, migrations, audit evidence,
  and release safety.

Migration: `core.0072_miniapp_drafts` is required before this recovery feature
works. It has **not** been applied to production by this change. To undo after
an approved migration, confirm drafts are disposable and run:

```powershell
python manage.py migrate core 0071_accesscontrolpolicystate_and_more
```

Migration: `core.0073_workflow_integrity`,
`core.0074_backfill_workflow_integrity`, and
`core.0075_tat_workflow_receipts` are required before workflow revision checks,
transition receipts, and SLA records work. They have **not** been applied to
production by this change. To undo after an approved migration, first export
any new transition/SLA audit evidence that must be retained, then run:

```powershell
python manage.py migrate core 0072_miniapp_drafts
```
