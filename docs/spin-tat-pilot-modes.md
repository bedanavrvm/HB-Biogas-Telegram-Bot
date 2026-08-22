# SPIN and TAT Pilot Modes

## Purpose

SPIN and TAT Tracker each have an independent operating mode. The mode marks newly created operational records as either `Pilot` or `Production` without rewriting historical records.

This makes it possible to test incomplete role participation and provisional processes without allowing those records to contaminate production queues, SLA reporting, dashboards, or Portal references later.

The initial migration classifies all existing SPIN and TAT operational records as Pilot. It creates one protected active pilot cycle for each workflow.

## Key rules

- SPIN and TAT modes are controlled separately.
- A record permanently keeps the mode and pilot cycle captured when it was created.
- Production records are always operational and are never purge-eligible.
- While a workflow is in Pilot mode, only its current Pilot cycle appears alongside Production records in normal queues. In Production mode, Pilot rows are hidden from normal queues.
- A closed Pilot cycle is Admin-visible and read-only, but excluded from operational queues, TAT SLA calculations, escalations, metrics, and Portal references.
- The currently active Pilot cycle can never be purged.
- Google Drive files and generic media metadata are never deleted by pilot cleanup.
- Only an active Django Superuser can change modes, rotate cycles, acknowledge Sheet readiness, or purge data.
- Every mode change, cycle rotation, and purge is audit-recorded with the actor, time, and reason.

## Django Admin location

Open Django Admin and use:

`Configuration` -> `SPIN/TAT pilot modes`

The switchboard shows the current SPIN and TAT modes, active cycle identifiers, mode versions, and active purge locks.

## Changing Pilot to Production

1. Open `SPIN/TAT pilot modes`.
2. Change only the workflow mode you intend to release.
3. Enter a clear operational reason.
4. Save.
5. Confirm the success message and verify the mode badge in that workflow's Mini App.

Changing mode affects only records created after the change. Existing Pilot rows stay Pilot. A production switch therefore cannot silently legitimize test data.

Changing back from Production to Pilot starts a new pilot cycle automatically. New records enter that new cycle; Production rows remain visible and usable.

## Closing a Pilot cycle

Closing a cycle is deliberately separate from deleting it.

1. Keep the workflow in Pilot mode.
2. Open `SPIN/TAT pilot modes`.
3. Select `Rotate SPIN pilot cycle` or `Rotate TAT pilot cycle`.
4. Enter the reason for closing the current test cycle.
5. Confirm rotation.

Rotation immediately creates a new protected active cycle. Records from the previous cycle disappear from normal Mini App queues and become read-only and purge-eligible. The newly active cycle cannot be purged.

Use rotation when a new clean test round is required. Do not use a production-mode switch merely to make an active cycle purgeable.

## Mini App behaviour

Both SPIN and TAT display a visible `Pilot` or `Production` indicator.

The Mini App sends the current mode version with writes. If a Superuser changes the mode or rotates the cycle while a user has an old screen open:

- an open closed-cycle record may still be read directly;
- it is read-only;
- a write is rejected with HTTP `409` and code `WORKFLOW_MODE_CHANGED`; and
- the Mini App reloads the current queue/configuration instead of silently writing into the wrong scope.

This prevents a cached browser or Telegram WebView from crossing a mode boundary.

## Permanent cleanup procedure

Pilot cleanup permanently removes eligible Django operational rows and, where configured, their exact Google Sheet rows. It is intentionally multi-stage.

### 1. Select the scope

From the switchboard, open `Pilot cleanup` and choose:

- SPIN;
- TAT Tracker; or
- SPIN and TAT.

The preview contains only closed Pilot-cycle record identifiers. It never contains customer names, IDs, phone numbers, or document content.

### 2. Review every Sheet destination

For each listed Sheet tab:

1. Check fixed formulas, named ranges, summaries, and downstream tabs manually.
2. Confirm that deleting data rows will not leave a fixed range pointing at the wrong rows.
3. Record what was checked in the acknowledgement note.
4. Select `Acknowledge`.

The acknowledgement is bound to fingerprints of the current tab layout and formulas. If the Sheet configuration or formulas change, the acknowledgement becomes stale and must be repeated.

Even records marked locally unsynchronized are checked against a resolvable destination before Django deletion. A configured but unresolved Sheet destination blocks cleanup.

### 3. Start the purge

1. Review the frozen record and Sheet-tab counts.
2. Enter a reason.
3. Type `PURGE CLOSED PILOT DATA` exactly.
4. Select `Purge verified closed pilot data` once.

The service locks the selected workflow or workflows so purge runs cannot overlap.

For each Sheet group it:

1. finds rows by the stable SPIN request ID or TAT case ID, never only by a stored row number;
2. deletes matching rows from the bottom upward;
3. re-reads the Sheet and proves all target IDs are absent;
4. repairs stored row pointers for surviving Django records; and
5. only then deletes the corresponding Django operational rows.

If Sheet verification fails, Django rows remain. The run is marked `Failed` or `Partial` and retains resumable progress.

### 4. Retry safely

Use `Retry safely` on a failed or partial run after correcting the external problem. Already verified Sheet groups are not deleted again. A run left in `Running` by a terminated worker can be resumed after its five-minute heartbeat lease becomes stale.

Do not create another run for the same workflow while a purge lock exists.

## What cleanup deletes

Depending on scope, cleanup deletes closed-cycle operational roots and their dependent operational data:

- SPIN credit requests;
- SPIN batch-review items in the closed cycle;
- TAT cases and their dependent approval certificates/events;
- closed-cycle TAT SLA escalation projections; and
- closed-cycle TAT daily metrics.

Database cascade constraints continue to govern dependent records.

## What cleanup preserves

- all Production records;
- all records in the active Pilot cycle;
- immutable workflow mode/change/purge audit events;
- the non-PII purge manifest and outcome summary;
- Google Drive files;
- generic media metadata and attachments; and
- all records belonging to other Mini Apps/workflows.

This cleanup is not a general database reset and must never be expanded to Origination, Portal, complaint cases, orders, payments, or other workflows.

## Developer integration rules

Creation paths must capture a mode snapshot inside the same transaction as the new row. Do not accept `data_mode`, `pilot_cycle_id`, or `data_scope_key` from a Mini App payload.

Normal reads must use the centralized helpers in `core/services/workflow_data_mode.py`:

- `operational_spin_requests()`;
- `operational_spin_review_items()`;
- `operational_tat_cases()`; or
- `operational_q()` for related projections.

Mutable detail/write paths must call `assert_record_writable()`. API views must preserve the `WORKFLOW_MODE_CHANGED` code and return HTTP `409`.

Do not reproduce the visibility expression independently in dashboards, reports, SLA jobs, repair jobs, Portal references, or new endpoints. Centralized scoping is the control that prevents closed Pilot data from leaking into production operations.

Purge changes belong in `core/services/workflow_pilot_purge.py`. Any new Sheet-backed SPIN/TAT record must add stable external-ID discovery, bottom-up deletion, post-delete verification, and surviving-row-pointer repair before it can be included in cleanup.

## Release and verification checklist

1. Apply migrations.
2. Confirm both modes initially show Pilot.
3. Create one synthetic SPIN request and one synthetic TAT case; verify Pilot badges.
4. Rotate each Pilot cycle and verify the old records disappear from normal queues.
5. Open an old record directly; verify it is read-only.
6. Attempt a stale write; verify `409 WORKFLOW_MODE_CHANGED` and a safe reload.
7. Switch one workflow to Production and create a synthetic record; verify it is classified Production.
8. Verify Production plus only the current Pilot cycle appears in operational queries.
9. Perform Sheet formula/range review with a non-production test Sheet before using cleanup against configured operational tabs.
10. Verify cleanup never deletes Drive/media objects or Production/active-cycle records.
11. Verify dashboard, Portal, SLA, escalation, repair, and Mini App results exclude closed Pilot cycles.
12. Review `Workflow data mode events`, `Workflow pilot purge runs`, and `Workflow pilot formula readiness` in Admin for complete audit evidence.
