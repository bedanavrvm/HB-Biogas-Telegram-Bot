# ADR 0007: Sheet register governance and verified TAT duplicate-row repair

Status: Accepted - 30-July-2026

## Context

Django is the canonical source of workflow state while Google Sheets remains a
staff-facing operational register. The platform previously had no durable
field-level publication contract or audit evidence for schema drift and row
divergence. In TAT specifically, duplicate-case cleanup deleted duplicate
Sheet rows and adjusted stored row numbers from arithmetic. If rows shifted in
an unexpected way, a later Mini App update could target the deleted/stale row
instead of the surviving immutable case-ID row.

## Decision

Use an Admin-managed, publication-only `SheetRegisterContract` for every
registered Sheet tab. Its expected header order and field ownership state
which fields are backend-owned, formula-owned, derived, or immutable.
`SheetSyncAuditSnapshot` and privacy-preserving `SheetSyncDiscrepancy` rows
retain schema/header fingerprints and divergence evidence; raw customer values
are never copied into those audit rows.

Audits are deliberate read-only operator actions (`audit_sheet_registers` and
`audit_drive_permissions`). They do not introduce a scheduled worker, inbound
Sheet import, or Drive permission remediation. `seed_sheet_register_contracts`
is dry-run by default and creates only local contract rows when explicitly
called with `--apply`; it does not contact or edit Google Sheets.

TAT duplicate cleanup remains separately confirmed and destructive. After
each deletion it re-reads the live tab, requires exactly one surviving row for
each immutable Case ID, updates the Django row pointer only after that proof,
and re-publishes linked cases using the normal canonical sync path (including
the existing secondary case-index publication). `LiveSheetRecordChange`
records every success or failure. A failed verification or re-publish is never
reported as a successful cleanup.

## Consequences

- A Sheet schema/header change, duplicate row key, stale row pointer, missing
  case row, orphan row, or backend-owned TAT value mismatch is observable and
  retained as local audit evidence.
- Sheet/Drive access is limited to explicit operator commands/Admin actions;
  no production Google API request was made while implementing this decision.
- Deleting duplicate rows is still irreversible from Django's perspective. A
  verified surviving row can be re-published; a failed verification requires
  operator review rather than a guessed pointer or blind retry.
- Register contracts must be confirmed for each operational tab before strict
  audits can be relied upon. The controlled seed command is a starting point,
  not proof that a live worksheet has the expected layout.

## Alternatives considered

1. Continue calculating new row pointers from deleted-row offsets — rejected:
   Sheets can be concurrently edited, sorted, or partially fail a delete.
2. Re-enable Sheet-to-Django imports to repair divergence automatically —
   rejected: it violates the settled Django source-of-truth boundary.
3. Store raw expected/actual values in audit logs — rejected: audit evidence
   must not become another unbounded store of customer PII.

## Release and rollback

No production migration, Render deployment, live Sheet cleanup, or Drive audit
is authorised by this ADR. Before a production release, take a PostgreSQL
backup and verify on a copied Sheet: schema drift, a healthy TAT contract,
duplicate cleanup with an expected survivor, a forced verification failure,
and a forced re-publish failure. Confirm every required register has a
reviewed contract, then record the audit outcome.

Migration `core.0082_sheet_register_governance` adds local contract and audit
tables only. To undo after an approved migration, first export the audit
evidence required for the period, then run:

```powershell
python manage.py migrate core 0081_jawabuapprovalcondition_jawabuapprovaldelegation_and_more
```

The reverse migration removes only the local governance tables. It does not
change Google Sheets, Drive files, case records, or prior external cleanup.
