# ADR 0025: Non-destructive Portal working-list archival

**Status:** Accepted for code merge and local/staging validation only.
Production migration application requires separate explicit release approval.

## Context

Portal report definitions already retain an active/archived lifecycle, but the
catalogue made archival available only after opening a report. Staged FarmUp
and SysUp imports had a different meaning of "archive": retaining the source
file in the restricted Drive folder. They had no separate working-list state,
so an IT user could not safely clear a reviewed batch from the active Imports
list without deleting its source, parsed review evidence, or Drive metadata.

The Portal needs clear archive actions while retaining compliance evidence and
while keeping imports strictly review-only.

## Decision

- A saved Portal report can be archived directly from its catalogue card as
  well as its detail page. The existing report archival service remains the
  only write path: it uses optimistic version checking and append-only
  compliance evidence. No physical report-definition deletion is introduced.
- Add a separate backend-owned working-list archive state to
  `JawabuFarmerUploadBatch`: archived flag, timestamp, and actor. It is
  deliberately separate from the existing Drive `archive_*` metadata.
- An IT-authorised Portal request archives a staged import transactionally,
  records one idempotent compliance event, and then removes it from the active
  Imports list. It does not delete the raw source, parsed review data,
  integration-operation history, or restricted Drive copy; it never commits a
  customer record or calls Drive.
- Ordinary Imports listing excludes working-list archived batches. A direct
  scoped detail read remains possible for retained evidence and operational
  support, subject to the existing IT capability and group scope.

## Consequences

Portal users can clean active lists without losing auditability or exposing a
destructive action on sensitive source files. "Drive archived" continues to
mean the restricted storage copy succeeded; "archived from Imports" means only
that the batch was removed from the active Portal work queue.

## Alternatives considered

- **Hard-delete reports/import batches:** rejected because it would remove
  operational evidence and make retry/investigation materially harder.
- **Reuse `status=cancelled` for imports:** rejected because it describes the
  source import workflow, not whether a retained batch should appear in the
  Portal working list.
- **Hide client-side only:** rejected because another device/session would
  still list the batch and the action would have no auditable record.

## Migration and rollback

`core.0100_portal_import_working_list_archival` adds nullable archival
metadata and an index only. Existing batches remain visible, no backfill runs,
and the migration makes no case, customer, Sheet, Drive, document, or payment
change.

To undo a non-production application before relying on the new fields:

```text
python manage.py migrate core 0099_portal_reporting
```

Do not reverse after production use merely to restore a UI. Prefer restoring a
prior application commit and preserve archive/compliance evidence.
