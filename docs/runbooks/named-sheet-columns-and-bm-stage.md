# Named Sheet columns and BM stage rollout

## Scope and source of truth

Django owns TAT decisions, timestamps, attribution and timers. The new BM stage
is not the draft credit-assessment feature and has no new signing gate.
Existing cases keep their captured path; this rollout changes future cases only.

## BM action access after deployment

Migration `0204_tat_bm_analysis_capability` supplies the missing default TAT BM
permission during the normal deployment release. No separate rollout command is
needed to repair action access on a case that already includes the BM stage.
The built-in capability stays discoverable even when a product is unavailable or
the worker's product catalogue was cached before publication. A current in-scope
TAT BM or IT grant is still required; deliberate BM denials remain unchanged.
Select Approved or Declined; Django records the decision time automatically.
This action does not require an Origination role, signature or signing setup.

TAT, Complaints, Portal and Origination grants are independent. The optional
product-successor procedure below is configuration authoring, not a prerequisite
for this permission repair. It preserves existing captured case paths. The normal
release runs checked-in migrations through `release.sh`; the build/start scripts
remain free of database mutation. The hosted pre-deploy configuration must still
be verified by the deployment owner.

Every live field is resolved by a unique named header. Names are normalized for
Unicode, case and whitespace. Known aliases are explicit, not guesses. Two
matching aliases, duplicate normalized names, missing required names, populated
unnamed columns or a changed header layout stop the affected operation. Fix the
names and retry; do not renumber mappings or clear workflow/audit data.

Google Sheets does not provide an atomic schema compare-and-write. Pause manual
column/row sorting and structural edits during publication and cleanup. A header
check reduces the race window but cannot replace this operational precaution.

## Before activation

1. Deploy the code through the normal release procedure. These changes have not
   been applied to any production configuration or external service.
2. In each live TAT Register, manually add these three unique headers anywhere:

   - `BM analysis approval`
   - `BM analysis approval timestamp`
   - `BM analysis approval TAT Minutes`

3. Keep existing headers/data. Required older timestamps and per-stage minute
   columns must also have distinct names. The `sheet_header` setting can bind
   a custom stage's column explicitly. An alias and its canonical header must
   not both represent the same field on one tab.
4. In TAT Control Center, confirm BM routing for each branch/product. Existing
   role-wide BM responsibility can cover the new stage; a roster restricted to
   the later BM response does not. AccessGrants still control authorization.
5. Set the BM stage target in Settings when a target is agreed. Do not invent a
   target to obtain a rating: without one, the completed action is timed but unrated.
6. Preview the named-column audit. Default execution reads configuration only:

   ```powershell
   .\.venv\Scripts\python.exe manage.py audit_named_sheet_columns
   ```

   `--configuration <id> --live --bm-stage` explicitly reads only that configuration's Sheet
   headers. It does not repair or write cells. Review every reported issue.

## Product successor

Preview first; repeat `--product` for the exact selected product codes:

```powershell
.\.venv\Scripts\python.exe manage.py rollout_tat_bm_analysis --product business
```

Use `--actor <active-superuser-username> --apply` to prepare an editable successor.
Review it in Product setup. The source is not rewritten. Use the same command
with `--apply --publish` for explicit activation. Repeating an unchanged completed
command does not create another version. BM defaults are already provisioned by
deployment migration 0204; the command is not required to grant the new action.
Edited prepared drafts are not silently published by this command; publish them
through the normal reviewed Product setup.

Unrelated drafts and scheduled versions need review. A published Origination
definition bound to the shared source version blocks automatic replacement,
because retiring its terms would prevent new Origination applications. Coordinate
that definition's successor explicitly; this tool never silently rebinds it.
No existing TAT or Origination application is converted.

After publication verify a new case follows:

`M-PESA sent → BM analysis approval → Admin verification → Credit Analysis`

Confirm Approved advances, Declined closes/stops timing, Admin cannot bypass BM,
the later BM response is still separate, and an older case retains its old path.
Existing notification dispatches route the task to BM; no new scheduler is added.

## Apps Script cutover

The supported TAT script is `tat_tracker_apps_script.gs`, for workbook maintenance
only. The old `jbl_apps_script_v5.gs` and `hocc tracker/script.gs` source copies
were retired by explicit approval; Git retains their history. Repository removal
does **not** undeploy a Google web app or remove its installed triggers. An owner
must disable the old deployments/triggers before installing the supported script.
Do not restore their old workflow actions or hard-coded staff permissions.

Other supported scripts resolve their declared live columns by name. Existing
populated sheets are validated, not relabelled. Their header-row conventions
remain explicit; Master Data uses row 1, with data starting on row 2. `_REFERENCE`
dropdown sources also need named headers. Never infer a field from its old letter.

On the order-maintenance Staff tabs, replace numeric/letter entries in Editable
Columns with exact column names or the existing named role groups before applying
protections. Permission reads include the full live tab width after columns move.
If the optional legacy AUDIT LOG projection is used, add a unique `Event ID`
header. It retains Django event IDs so delivery retries do not duplicate rows.
Do not backfill invented IDs for older log entries. CASE_INDEX duplicate Case IDs
must be repaired explicitly; publication never chooses the first matching row.

FarmUp CSVs with two `Sign Date` headings must be corrected: label the visit date
`HBG Visit Date` and the other date according to its actual purpose, for example
`Contract Sign Date`. A lone legacy `Sign Date` remains supported. Do not use
synthetic suffixes to resolve an ambiguous import or merge different dates.

## Verification and recovery

### Saved remarks

All authorized staff who can view an in-scope TAT case may add a remark, including
on Declined and Disbursed cases. Deleted, unresolved and closed-Pilot records
remain read-only. Earlier text is retained; new comments append their saved time,
name and applicable TAT roles at the end, separated by a line. Remarks appear
in Activity and never change stages, targets, completion clocks or scores.

The canonical save returns without calling Google. The existing
`process_tat_notifications` command now also drains event-keyed remark operations.
No second runner or new schedule is needed. Enable the existing group's TAT Sheet
projection to publish notes; the required unique headers are `Case ID` and
`Remarks / Delays` (the explicit legacy alias `Remarks` remains supported; keep
only one of these headers). The publisher locates the current row by Case ID and writes
literal text only to the remarks cell. It does not write stage/time cells or
append a new row when the case's normal publication has not arrived yet.

For a provider failure, the saved note remains in Django. Repair unsafe names
or duplicate Case IDs, then an active Superuser selects the affected
IntegrationOperation and uses **Retry selected TAT remark Sheet updates** in
Django Admin. This requeues only failed remark projections, records the retry
and leaves unrelated operations untouched. Never recreate or resubmit a comment to repair
its Sheet delivery. Disabled or replaced group configurations, deleted cases
and closed Pilot scopes cannot publish stale pending notes. See ADR 0051.

The isolated test runner supports `--fresh-database` to recreate only its named
local test database. Use it after transaction suites have flushed migration
fixtures; it never targets the normal configured application database.

Test outputs are written under `test-results/` as `.txt`; only synthetic data and
mock providers are used. PostgreSQL locking is checked on a task-owned local
cluster, not SQLite or a production database. See `KNOWN_GAPS.md` for the exact
verified scope and outstanding baseline failures.

A failed Sheet dispatch does not undo a saved case. Repair names, then retry the
existing durable operation. Do not recreate the case. Never roll back to positional
writes after columns have moved. Existing final recognition snapshots are immutable;
new stage facts enter the existing live reporting and recognition projections.
