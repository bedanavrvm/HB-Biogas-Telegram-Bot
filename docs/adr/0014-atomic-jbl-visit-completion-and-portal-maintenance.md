# ADR 0014: Atomic JBL visit completion and Portal maintenance mode

**Status:** Accepted for code merge and local/staging validation; production
migration application requires separate release approval

## Context

The prior Portal visit flow uploaded LAF/photo evidence and logged the JBL
visit through separate write routes. A network interruption between those
steps could leave sensitive evidence in Drive without a corresponding
canonical visit record. Telegram's mobile WebView can also discard selected
file handles after an officer temporarily leaves the Mini App.

Field staff need a clear “HBG visit received; JBL visit to be scheduled”
handoff state, without allowing that state to be mistakenly logged as a visit
outcome. IT also needs a visible, narrowly-scoped way to pause new Portal
writes while keeping operational records readable during maintenance.

## Decision

- Use one multipart `complete-visit` route for all new JBL visit completion.
  It validates the stage, revision, date ordering, status, GPS fallback and
  media categories before Drive receives files, then repeats transition checks
  before it writes canonical state.
- The historical standalone “log visit” and “upload media” write routes return
  an upgrade response. They cannot create new split evidence/visit states.
- Every completion carries the existing Mini App retry key. Completed retries
  return success and evidence uploads reuse their content hashes. If Drive
  succeeds but the canonical transition fails, the response truthfully says
  that evidence was retained and the visit was not logged.
- A FarmUp HBG-visit import defaults only a blank, unvisited case to `JBL to
  Schedule Visit`; it never overwrites a recorded JBL outcome. The backfill
  command is dry-run by default and has a run-scoped safe revert.
- `PortalMaintenanceState` is a singleton, IT-only, read-only mode. New Portal
  writes receive a safe 503 while reads and already-admitted requests remain
  able to finish. Every state change is immutable compliance evidence.
- Text/GPS form values are recovered from the current browser session after a
  WebView return. Files are intentionally never persisted in the browser.

## Consequences

The mobile form can send LAF and photo together and cannot falsely report a
completed visit until the authoritative case transition succeeds. On a partial
external failure, staff get an actionable retry message rather than a false
success. The UI labels the scheduling handoff as a queue state, not an
officer-selectable visit result.

Drive is not transactional with PostgreSQL, so this is not a literal global
transaction. The preflight, revision recheck, retry key and content-hash reuse
are the compensating controls. Telegram cannot restore a browser `FileList`
after the operating system/WebView drops it; staff must reselect evidence.

## Alternatives considered

- **Keep two routes and rely on staff retrying:** rejected because retries
  cannot prove whether evidence and a visit were both committed.
- **Upload files before validation:** rejected because invalid/stale forms
  would leave avoidable sensitive files in storage.
- **Persist file handles in session/local storage:** rejected because browsers
  prohibit reliable serialisation/restoration of selected files.
- **Use Django technical-superuser status for maintenance:** rejected because
  Portal roles and Django technical flags are deliberately separate.

## Rollback

Migration `core.0092_portal_maintenance_state` is limited to the maintenance
singleton and missing IT capability seed rows. It does not change a case,
payment, document, user identity, Sheet, or Drive file.

To undo the schema locally or in an explicitly approved rollback:

```powershell
python manage.py migrate core 0091_pause_portal_workspace_to_it
```

The migration deliberately retains policy snapshots and append-only compliance
evidence. Prefer an application-code rollback for a UI/API issue. Do not run
the FarmUp scheduling backfill with `--apply`, publish a register, or apply
this migration to production without separate release approval.
