# ADR 0017: Portal additive case comments

**Status:** Accepted for code merge and local/staging validation; production
migration application and Apps Script deployment require separate release approval.

## Context

`Additional Comments` had been used inconsistently as a free-text HBG import
field. It could not show the chronological remarks made during the later JBL,
Head of Rural, and payment workflow. Reading a current case therefore required
opening multiple stages and did not preserve one useful register-level account
of what staff said and when.

## Decision

- Add an append-only Django comment ledger for non-empty staff remarks created
  by existing authorised post-JBL actions: JBL visit, final review, payment
  review, and return-for-rework.
- Snapshot the accountable Portal function at write time: JBL Officer, Credit
  Analyst, Head of Rural, Operations Staff, or IT. It is not inferred from a
  later AccessGrant lookup.
- Publish the ledger to `Additional Comments` in chronological order using
  Kenya-local timestamps and `user / role - comment` entries.
- `Additional Comments` is backend-owned. Existing Sheet-only text is replaced
  on publication and is not backfilled into the canonical ledger. HBG comments
  use only an explicit HBG-comment header where one exists.
- No standalone comment action or new capability is added; the existing action
  permission remains the authority to add its accompanying remark.

## Consequences

The register becomes a readable projection of staff remarks without making
Google Sheets a workflow writer. Existing stage fields remain available for
their forms, generated documents, and detailed case history. Retries use the
existing request identity and cannot create a second ledger line.

## Alternatives considered

- **Keep a manually editable Sheet field:** rejected because its author,
  timestamp, and authority cannot be verified.
- **Backfill existing stage comments:** rejected because the business chose to
  start the ledger from release day rather than fabricate missing attribution.
- **Add a general discussion feature:** deferred; comments remain tied to
  existing workflow actions in this release.

## Rollback

Migration `core.0095_jawabucasecomment` creates an empty comment ledger only.
It does not rewrite cases, existing Sheet values, financial documents, Drive
files, or audit evidence. To undo an explicitly approved application:

```powershell
python manage.py migrate core 0094_alter_jawabuapprovalrecord_decision_and_more
```

Prefer an application-code rollback for a display issue. Do not apply the
migration or deploy the Apps Script to production without separate approval.
