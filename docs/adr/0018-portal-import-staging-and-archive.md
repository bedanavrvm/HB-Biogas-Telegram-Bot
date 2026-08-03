# ADR 0018: Portal import staging and controlled Drive archive

**Status:** Accepted for code merge and local/staging validation. Production
migration application, Drive-folder configuration, and production release each
require separate approval.

## Context

`/farmup` and `/sysup` already parse operational source files into staged
`JawabuFarmerUploadBatch` records. Their Telegram-command routes are not a
convenient review surface for IT, and a source file was not retained on the
batch for later evidentiary Drive archival.

The Portal needs a simple upload/review surface, but a Portal upload must not
silently commit, overwrite, or create customer cases. Free Render also cannot
hold a web worker while a file is parsed and a Google Drive upload waits.

## Decision

- Add the IT-only `portal.imports.view` capability and an **Imports** Portal
  tab. The tab stages either a FarmUp CSV or SysUp CSV/XLSX file using the
  existing parser services and displays their existing parsed review rows.
- The tab is review-only in this release. It exposes no approve/commit action
  and never calls the existing FarmUp/SysUp commit services.
- Store a bounded original upload payload, SHA-256 digest, creator, retry key,
  and Drive-archive state on `JawabuFarmerUploadBatch`. The raw source supports
  later archive retry; it is never returned from the Portal API.
- Archive accepted sources to the separately configured
  `JAWABU_IMPORTS_DRIVE_FOLDER_ID` through a durable `IntegrationOperation`.
  The Mini App makes one bounded follow-up attempt after staging; a later
  permitted visit can retry a retained pending/failed operation. Local batch
  staging never waits for Drive.
- Respect the requesting IT user's AccessGrant group scope for both batch
  listing and destination selection. Archive operations are scope-checked
  before any Drive call.
- Seed only a missing `portal.imports.view` allow for Portal role `IT`.
  Existing allow/deny policy rows remain authoritative. The policy version and
  append-only policy/compliance evidence are updated so a subsequent Portal
  metadata fetch reflects the new capability.

## Consequences

IT can review incoming source data in the Mini App and see whether its archive
is pending, retained, or needs attention. Existing Telegram command review and
commit paths remain unchanged. Raw sources add controlled PII-bearing database
storage, so access is narrowly capability/scope-gated and the Drive root must
be a restricted Shared Drive folder.

This does not create a background queue. A dedicated worker remains a future
reliability upgrade; the durable operation state makes retries visible and
safe on the current free Render deployment.

## Alternatives considered

- **Commit directly from the new tab:** rejected for now. It would combine a
  high-impact customer write with staging and needs a separately approved
  maker-checker design.
- **Only retain the parsed JSON:** rejected because it is not a faithful copy
  of the supplied system file and cannot support a later Drive archive.
- **Drive upload inside the staging request:** rejected because it can exceed
  the free Render Gunicorn worker budget and make a valid staged import look
  failed.
- **Use the ordinary media Drive root:** rejected because imports should have a
  stricter, auditable retention boundary than field visit media.

## Rollback

Migration `core.0096_portal_import_archives` adds archival metadata, a bounded
raw source payload, and one missing IT capability policy row. It does not
write customers, cases, orders, payments, Sheets, or Drive files during
migration.

To undo an explicitly approved migration before relying on the new fields:

```powershell
python manage.py migrate core 0095_jawabucasecomment
```

The reverse intentionally preserves policy snapshots/audit evidence and does
not delete Drive files. Prefer an application-code rollback for a Portal UI
issue. Do not apply this migration to production or configure a live Drive
folder without separate release approval.
