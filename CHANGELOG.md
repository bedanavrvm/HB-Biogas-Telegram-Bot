# Changelog

This file records notable, user-visible and operational changes. Entries are
added while work is performed; deployment remains a separate, explicitly
approved action.

## Unreleased — 29-July-2026

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
