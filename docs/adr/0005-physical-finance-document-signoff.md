# ADR 0005: Physical finance-document sign-off retention

Status: Accepted - 29-July-2026

## Context

JBL requisitions and payment schedules are generated from controlled Django
case data but are physically printed, signed, and stamped. The signed copy
must be reviewable later without overwriting the generated Excel, confusing a
scan for a cryptographic signature, or allowing a Drive outage to destroy the
only retained evidence.

## Decision

Keep e-signatures deliberately out of scope. A generated requisition or final
payment workbook remains the original operational artifact. An authorised
Portal role uploads one PDF/JPG/PNG scan of the physically signed and stamped
copy, explicitly attests that it is complete/readable and matches the displayed
version, and the platform snapshots both workbook bytes and scan bytes with
SHA-256 hashes.

The sign-off record is append-only and Drive-backed with local retry metadata.
It becomes approved only after its Drive upload succeeds. The initial
responsible role is Portal `BUSINESS_ADMIN` (the current Head-of-Rural
authority), but
the requisition and payment role policies are changed only through the existing
maker-checker access-control request flow. A new workbook version never erases
an earlier approved scan.

## Consequences

- Existing records without retained source bytes remain visible as legacy and
  are not automatically declared signable; regenerate them deliberately when
  a new traceable artifact is required.
- This proves who attested the physical scan and which exact workbook they
  reviewed. It does not assert that handwriting/stamps are legally verified.
- Documents and signing evidence are retained; no automatic deletion is
  introduced. Retention/archive policy remains a separate approved decision.

## Alternatives considered

1. E-signature service now - deferred by operational decision.
2. Store a signature/stamp image on the workbook - rejected because it could
   falsely represent an individual signature and would not prove paper review.
3. Keep only a Drive URL - rejected because it cannot bind a scan to immutable
   source bytes or tolerate a retry/failure safely.

## Release and rollback

No production migration or Render deployment is authorised by this ADR. Before
production application, confirm a PostgreSQL backup and test one authorised
upload, denied upload, Drive failure/retry, and history view with non-production
files.

To undo after an approved production migration, first export any sign-off audit
records and scans that must be retained, then run:

```powershell
python manage.py migrate core 0079_remove_workflowtatdailymetric_unique_workflow_tat_daily_metric_and_more
```

The reverse migration removes the sign-off schema and seeded capability/policy;
it does not alter existing requisition, payment, farmer, Sheet, or Drive data.
